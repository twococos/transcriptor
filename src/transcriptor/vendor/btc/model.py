# Copyright (c) 2019 Jonggwon Park — llicència MIT (vegeu LICENSE en aquest directori).
# Adaptat de btc_model.py i utils/transformer_modules.py de BTC-ISMIR19.
"""Model BTC, només inferència."""

import math

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

# Hiperparàmetres de run_config.yaml amb vocabulari gran (170 classes)
CONFIG_MODEL = {
    "feature_size": 144,
    "timestep": 108,
    "num_chords": 170,
    "num_layers": 8,
    "num_heads": 4,
    "hidden_size": 128,
    "total_key_depth": 128,
    "total_value_depth": 128,
    "filter_size": 128,
}
CONFIG_AUDIO = {
    "song_hz": 22050,
    "inst_len": 10.0,
    "n_bins": 144,
    "bins_per_octave": 24,
    "hop_length": 2048,
}

_ARRELS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_QUALITATS = ["min", "maj", "dim", "aug", "min6", "maj6", "min7", "minmaj7", "maj7", "7",
              "dim7", "hdim7", "sus2", "sus4"]


def idx_a_acord(idx: int) -> str:
    """Índex de classe → etiqueta tipus Harte ('A:min', 'C', 'N' = sense acord, 'X' = desconegut)."""
    if idx == 169:
        return "N"
    if idx == 168:
        return "X"
    arrel, qualitat = _ARRELS[idx // 14], _QUALITATS[idx % 14]
    return arrel if qualitat == "maj" else f"{arrel}:{qualitat}"


def _gen_bias_mask(max_length):
    mask = np.triu(np.full([max_length, max_length], -np.inf), 1)
    return torch.from_numpy(mask).float().unsqueeze(0).unsqueeze(1)


def _gen_timing_signal(length, channels, min_timescale=1.0, max_timescale=1.0e4):
    position = np.arange(length)
    num_timescales = channels // 2
    increment = math.log(float(max_timescale) / float(min_timescale)) / (float(num_timescales) - 1)
    inv_timescales = min_timescale * np.exp(np.arange(num_timescales).astype(np.float64) * -increment)
    scaled_time = np.expand_dims(position, 1) * np.expand_dims(inv_timescales, 0)
    signal = np.concatenate([np.sin(scaled_time), np.cos(scaled_time)], axis=1)
    signal = np.pad(signal, [[0, 0], [0, channels % 2]], "constant", constant_values=[0.0, 0.0])
    return torch.from_numpy(signal.reshape([1, length, channels])).float()


class LayerNorm(nn.Module):
    def __init__(self, features, eps=1e-6):
        super().__init__()
        self.gamma = nn.Parameter(torch.ones(features))
        self.beta = nn.Parameter(torch.zeros(features))
        self.eps = eps

    def forward(self, x):
        mean = x.mean(-1, keepdim=True)
        std = x.std(-1, keepdim=True)
        return self.gamma * (x - mean) / (std + self.eps) + self.beta


class SoftmaxOutputLayer(nn.Module):
    def __init__(self, hidden_size, output_size):
        super().__init__()
        self.output_size = output_size
        self.output_projection = nn.Linear(hidden_size, output_size)
        # No s'usa a la inferència, però és al checkpoint
        self.lstm = nn.LSTM(input_size=hidden_size, hidden_size=hidden_size // 2, batch_first=True,
                            bidirectional=True)

    def forward(self, hidden):
        """Retorna les probabilitats per classe."""
        return F.softmax(self.output_projection(hidden), -1)


class MultiHeadAttention(nn.Module):
    def __init__(self, input_depth, total_key_depth, total_value_depth, output_depth, num_heads,
                 bias_mask=None):
        super().__init__()
        self.num_heads = num_heads
        self.query_scale = (total_key_depth // num_heads) ** -0.5
        self.bias_mask = bias_mask
        self.query_linear = nn.Linear(input_depth, total_key_depth, bias=False)
        self.key_linear = nn.Linear(input_depth, total_key_depth, bias=False)
        self.value_linear = nn.Linear(input_depth, total_value_depth, bias=False)
        self.output_linear = nn.Linear(total_value_depth, output_depth, bias=False)

    def _split_heads(self, x):
        b, n, d = x.shape
        return x.view(b, n, self.num_heads, d // self.num_heads).permute(0, 2, 1, 3)

    def _merge_heads(self, x):
        b, h, n, d = x.shape
        return x.permute(0, 2, 1, 3).contiguous().view(b, n, d * h)

    def forward(self, queries, keys, values):
        q = self._split_heads(self.query_linear(queries)) * self.query_scale
        k = self._split_heads(self.key_linear(keys))
        v = self._split_heads(self.value_linear(values))
        logits = torch.matmul(q, k.permute(0, 1, 3, 2))
        if self.bias_mask is not None:
            logits = logits + self.bias_mask[:, :, : logits.shape[-2], : logits.shape[-1]].to(logits)
        weights = F.softmax(logits, dim=-1)
        return self.output_linear(self._merge_heads(torch.matmul(weights, v)))


class Conv(nn.Module):
    def __init__(self, input_size, output_size, kernel_size):
        super().__init__()
        self.pad = nn.ConstantPad1d((kernel_size // 2, (kernel_size - 1) // 2), 0)
        self.conv = nn.Conv1d(input_size, output_size, kernel_size=kernel_size, padding=0)

    def forward(self, inputs):
        return self.conv(self.pad(inputs.permute(0, 2, 1))).permute(0, 2, 1)


class PositionwiseFeedForward(nn.Module):
    def __init__(self, input_depth, filter_size, output_depth):
        super().__init__()
        self.layers = nn.ModuleList([
            Conv(input_depth, filter_size, kernel_size=3),
            Conv(filter_size, output_depth, kernel_size=3),
        ])

    def forward(self, x):
        # L'original aplica ReLU també després de l'última capa: es manté per fidelitat als pesos
        for layer in self.layers:
            x = F.relu(layer(x))
        return x


class self_attention_block(nn.Module):  # noqa: N801 — nom fixat pel checkpoint
    def __init__(self, hidden_size, total_key_depth, total_value_depth, filter_size, num_heads, bias_mask):
        super().__init__()
        self.multi_head_attention = MultiHeadAttention(hidden_size, total_key_depth, total_value_depth,
                                                       hidden_size, num_heads, bias_mask)
        self.positionwise_convolution = PositionwiseFeedForward(hidden_size, filter_size, hidden_size)
        self.layer_norm_mha = LayerNorm(hidden_size)
        self.layer_norm_ffn = LayerNorm(hidden_size)

    def forward(self, x):
        x_norm = self.layer_norm_mha(x)
        x = x + self.multi_head_attention(x_norm, x_norm, x_norm)
        return x + self.positionwise_convolution(self.layer_norm_ffn(x))


class bi_directional_self_attention(nn.Module):  # noqa: N801
    def __init__(self, hidden_size, total_key_depth, total_value_depth, filter_size, num_heads, max_length):
        super().__init__()
        mascara = _gen_bias_mask(max_length)
        self.attn_block = self_attention_block(hidden_size, total_key_depth, total_value_depth,
                                               filter_size, num_heads, mascara)
        self.backward_attn_block = self_attention_block(hidden_size, total_key_depth, total_value_depth,
                                                        filter_size, num_heads,
                                                        torch.transpose(mascara, dim0=2, dim1=3))
        self.linear = nn.Linear(hidden_size * 2, hidden_size)

    def forward(self, x):
        return self.linear(torch.cat((self.attn_block(x), self.backward_attn_block(x)), dim=2))


class bi_directional_self_attention_layers(nn.Module):  # noqa: N801
    def __init__(self, embedding_size, hidden_size, num_layers, num_heads, total_key_depth,
                 total_value_depth, filter_size, max_length):
        super().__init__()
        self.timing_signal = _gen_timing_signal(max_length, hidden_size)
        self.embedding_proj = nn.Linear(embedding_size, hidden_size, bias=False)
        self.self_attn_layers = nn.Sequential(*[
            bi_directional_self_attention(hidden_size, total_key_depth, total_value_depth, filter_size,
                                          num_heads, max_length)
            for _ in range(num_layers)
        ])
        self.layer_norm = LayerNorm(hidden_size)

    def forward(self, inputs):
        x = self.embedding_proj(inputs)
        x = x + self.timing_signal[:, : inputs.shape[1], :].to(inputs)
        return self.layer_norm(self.self_attn_layers(x))


class BTC_model(nn.Module):  # noqa: N801
    def __init__(self, config=CONFIG_MODEL):
        super().__init__()
        self.timestep = config["timestep"]
        self.self_attn_layers = bi_directional_self_attention_layers(
            config["feature_size"], config["hidden_size"], config["num_layers"], config["num_heads"],
            config["total_key_depth"], config["total_value_depth"], config["filter_size"],
            config["timestep"],
        )
        self.output_layer = SoftmaxOutputLayer(config["hidden_size"], config["num_chords"])

    def forward(self, x):
        """x: [batch, timestep, 144] → probabilitats [batch, timestep, 170]."""
        return self.output_layer(self.self_attn_layers(x))

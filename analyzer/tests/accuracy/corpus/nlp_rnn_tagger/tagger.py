"""A BiLSTM part-of-speech tagger over packed variable-length sequences.

Packing is the part everybody copies from a gist: the lengths must be on the
CPU, the batch must be sorted unless `enforce_sorted=False`, and the padded
output has to be unpacked before the classifier sees it.
"""
from __future__ import annotations

import torch
import torch.nn as nn
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence

VOCAB_SIZE = 25000
TAGSET_SIZE = 17
PAD_INDEX = 0
EMBED_DIM = 128
HIDDEN_DIM = 256


class BiLSTMTagger(nn.Module):
    def __init__(self, vocab_size: int = VOCAB_SIZE, tagset: int = TAGSET_SIZE):
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, EMBED_DIM, padding_idx=PAD_INDEX)
        self.lstm = nn.LSTM(EMBED_DIM, HIDDEN_DIM, num_layers=2,
                            bidirectional=True, batch_first=True, dropout=0.2)
        self.dropout = nn.Dropout(0.3)
        self.classifier = nn.Linear(2 * HIDDEN_DIM, tagset)

    def forward(self, tokens, lengths):
        embedded = self.dropout(self.embedding(tokens))
        packed = pack_padded_sequence(embedded, lengths, batch_first=True)
        output, _ = self.lstm(packed)
        padded, _ = pad_packed_sequence(output, batch_first=True)
        return self.classifier(self.dropout(padded))


def sequence_loss(logits, tags):
    """Flatten the time axis and ignore the padding positions."""
    criterion = nn.CrossEntropyLoss(ignore_index=PAD_INDEX)
    flat_logits = logits.reshape(-1, logits.size(-1))
    flat_tags = tags.reshape(-1)
    return criterion(flat_logits, flat_tags)

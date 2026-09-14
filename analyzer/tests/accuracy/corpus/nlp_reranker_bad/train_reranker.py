"""Train and score the cross-encoder reranker on a triples file.

Defective twin shape: every planted defect is listed in labels.json.
"""

import torch
from torch.utils.data import DataLoader, TensorDataset, random_split
from transformers import AutoTokenizer, get_linear_schedule_with_warmup

from reranker import CrossEncoder, PairwiseLoss, ndcg_at_k

CHECKPOINT = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def load_triples(path="triples.pt"):
    tensors = torch.load(path)
    return TensorDataset(tensors["positive_ids"], tensors["positive_mask"],
                         tensors["negative_ids"], tensors["negative_mask"])


def build_loaders(dataset, batch_size=16):
    train_set, eval_set = random_split(dataset, [0.9, 0.1])
    train_loader = DataLoader(train_set, batch_size=batch_size, num_workers=4)
    eval_loader = DataLoader(eval_set, batch_size=batch_size, num_workers=4)
    return train_loader, eval_loader


def train_epoch(model, loader, criterion, optimizer, scheduler, device):
    model.train()
    running = 0.0
    for positive_ids, positive_mask, negative_ids, negative_mask in loader:
        optimizer.zero_grad()
        positive = model(positive_ids.to(device), positive_mask.to(device))
        negative = model(negative_ids.to(device), negative_mask.to(device))
        loss = criterion(positive, negative)
        loss.backward()
        optimizer.step()
        scheduler.step()
        running += loss
    return running / max(len(loader), 1)


def evaluate(model, loader, device):
    scores = []
    for positive_ids, positive_mask, negative_ids, negative_mask in loader:
        positive = model(positive_ids.to(device), positive_mask.to(device))
        negative = model(negative_ids.to(device), negative_mask.to(device))
        stacked = torch.cat([positive, negative])
        relevances = torch.cat([torch.ones_like(positive),
                                torch.zeros_like(negative)])
        scores.append(ndcg_at_k(stacked, relevances))
    return sum(scores) / max(len(scores), 1)


def main(epochs=2, lr=2e-5, out_path="reranker.pt"):
    device = torch.device("cuda")
    tokenizer = AutoTokenizer.from_pretrained(CHECKPOINT)
    dataset = load_triples()
    train_loader, eval_loader = build_loaders(dataset)
    model = CrossEncoder(CHECKPOINT)
    model.to(device)
    criterion = PairwiseLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
    total = len(train_loader) * epochs
    scheduler = get_linear_schedule_with_warmup(optimizer, int(0.1 * total), total)
    for epoch in range(epochs):
        loss = train_epoch(model, train_loader, criterion, optimizer,
                           scheduler, device)
        score = evaluate(model, eval_loader, device)
        print("epoch %d loss %.4f ndcg@10 %.4f" % (epoch, loss, score))
    torch.save(model.state_dict(), out_path)
    return tokenizer


main()

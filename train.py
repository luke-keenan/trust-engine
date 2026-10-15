from pathlib import Path

import torch
from torch import nn

from model import RISK_TIERS, TrustModel

torch.manual_seed(7)
features, labels = [], []
for tier in range(len(RISK_TIERS)):
    risk = tier * 0.25 + torch.rand(5000) * 0.25
    noise = torch.randn(5000, 5) * 0.08
    base = torch.stack((
        risk * 0.85, 1 - risk * 0.8, risk * 0.8,
        risk * 0.7, 1 - risk * 0.85,
    ), dim=1)
    features.append((base + noise).clamp(0, 1))
    labels.append(torch.full((5000,), tier, dtype=torch.long))
data, targets = torch.cat(features), torch.cat(labels)
order = torch.randperm(len(data))
data, targets = data[order], targets[order]
ensemble, temperatures = [], []

for seed in range(3):
    torch.manual_seed(seed)
    model = TrustModel()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.002)
    for _ in range(24):
        for indices in torch.randperm(16000).split(512):
            optimizer.zero_grad()
            loss = nn.functional.cross_entropy(model(data[indices]), targets[indices])
            loss.backward()
            optimizer.step()
    calibration_x, calibration_y = data[16000:], targets[16000:]
    with torch.no_grad():
        logits = model(calibration_x)
    log_temperature = torch.zeros((), requires_grad=True)
    calibrator = torch.optim.LBFGS([log_temperature], lr=0.1, max_iter=30)

    def closure() -> torch.Tensor:
        calibrator.zero_grad()
        loss = nn.functional.cross_entropy(logits / log_temperature.exp(), calibration_y)
        loss.backward()
        return loss

    calibrator.step(closure)
    ensemble.append(model.state_dict())
    temperatures.append(float(log_temperature.detach().exp().clamp(0.05, 10)))

output = Path(__file__).with_name("ensemble.pt")
torch.save({"models": ensemble, "temperatures": temperatures}, output)
print(f"Saved calibrated {len(ensemble)}-model ensemble to {output}")

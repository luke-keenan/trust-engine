import torch
from torch import nn

INPUT_SIZE = 5
RISK_TIERS = ("Low", "Medium", "High", "Critical")


class TrustModel(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(INPUT_SIZE, 128), nn.ReLU(),
            nn.Linear(128, 64), nn.ReLU(),
            nn.Linear(64, len(RISK_TIERS)),
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.layers(features)

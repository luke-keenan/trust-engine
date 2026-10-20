from pathlib import Path

import torch

from model import INPUT_SIZE, RISK_TIERS, TrustModel


class RiskEnsemble:
    def __init__(self, models: list[TrustModel], temperatures: list[float]) -> None:
        self.models, self.temperatures = models, temperatures
        for model in models:
            model.eval()

    @classmethod
    def load(cls, path: Path) -> "RiskEnsemble":
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        models = [TrustModel() for _ in checkpoint["models"]]
        for model, state in zip(models, checkpoint["models"]):
            model.load_state_dict(state)
        return cls(models, checkpoint["temperatures"])

    def predict(self, signals: dict[str, float | int]) -> tuple[str, float, float]:
        vector = torch.tensor([[
            signals["model_drift"], signals["data_quality"],
            signals["access_anomaly_count"] / (signals["access_anomaly_count"] + 10),
            signals["output_variance"] / (1 + signals["output_variance"]),
            signals["fairness_metric"],
        ]], dtype=torch.float32)
        if vector.shape[1] != INPUT_SIZE:
            raise ValueError("Unexpected operational signal vector size")
        with torch.inference_mode():
            member_probs = torch.stack([
                torch.softmax(model(vector) / temperature, dim=1).squeeze(0)
                for model, temperature in zip(self.models, self.temperatures)
            ])
        probabilities = member_probs.mean(dim=0)
        entropy = -(probabilities * probabilities.clamp_min(1e-9).log()).sum() / torch.log(torch.tensor(4.0))
        tier = int(probabilities.argmax())
        risk_probability = float((probabilities * torch.tensor([0, 1 / 3, 2 / 3, 1])).sum())
        return RISK_TIERS[tier], risk_probability, float(entropy)

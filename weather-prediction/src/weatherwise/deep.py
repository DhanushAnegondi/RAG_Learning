"""LSTM for the long range: the last `lookback` days of temperature anomaly -> the next
`horizon` days of anomaly, all leads at once.

It competes with the simple damped-anomaly model and is used only if it wins on a validation
year (pipeline.choose_long). Anomaly = actual - climatology, so the network never has to learn
the seasons, only how departures from normal persist and fade.
"""

import numpy as np
import pandas as pd
import torch
from numpy.lib.stride_tricks import sliding_window_view
from torch import nn


class _Net(nn.Module):
    def __init__(self, hidden: int, horizon: int):
        super().__init__()
        self.lstm = nn.LSTM(input_size=1, hidden_size=hidden, batch_first=True)
        self.head = nn.Linear(hidden + 2, horizon)

    def forward(self, seq: torch.Tensor, season: torch.Tensor) -> torch.Tensor:
        _, (h, _) = self.lstm(seq.unsqueeze(-1))
        return self.head(torch.cat([h[-1], season], dim=1))


def _season(dates) -> np.ndarray:
    w = 2 * np.pi * pd.DatetimeIndex(dates).day_of_year.to_numpy() / 365.25
    return np.column_stack([np.sin(w), np.cos(w)]).astype(np.float32)


class AnomalyLSTM:
    """fit(anom) trains on a contiguous daily anomaly series; the last `val_share` of origins
    is held back for early stopping (restores the best epoch)."""

    def __init__(
        self,
        lookback: int = 30,
        horizon: int = 30,
        hidden: int = 32,
        epochs: int = 60,
        lr: float = 5e-3,
        patience: int = 6,
        val_share: float = 0.15,
        seed: int = 0,
    ):
        self.lookback, self.horizon, self.hidden = lookback, horizon, hidden
        self.epochs, self.lr, self.patience = epochs, lr, patience
        self.val_share, self.seed = val_share, seed

    def _windows(self, anom: pd.Series) -> tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]:
        """All (lookback window, next horizon values, origin date) without a missing day."""
        v = anom.to_numpy(dtype=np.float32)
        span = self.lookback + self.horizon
        if len(v) < span + 50:
            raise ValueError(f"not enough history: {len(v)} days, need over {span + 50}")
        w = sliding_window_view(v, span)
        ok = ~np.isnan(w).any(axis=1)
        origins = anom.index[self.lookback - 1 : len(v) - self.horizon][ok]
        return w[ok, : self.lookback], w[ok, self.lookback :], origins

    def fit(self, anom: pd.Series) -> "AnomalyLSTM":
        x, y, origins = self._windows(anom)
        self.scale = float(np.nanstd(anom.to_numpy(dtype=float))) or 1.0
        x, y = x / self.scale, y / self.scale
        season = _season(origins)
        n_val = max(1, int(len(x) * self.val_share))
        cut = len(x) - n_val - self.horizon  # gap: validation targets never overlap training
        tr = slice(0, max(cut, 1))
        va = slice(len(x) - n_val, len(x))
        torch.manual_seed(self.seed)
        rng = np.random.default_rng(self.seed)
        self.net = _Net(self.hidden, self.horizon)
        opt = torch.optim.Adam(self.net.parameters(), lr=self.lr)
        loss_fn = nn.L1Loss()
        xt, yt, st = (torch.from_numpy(a[tr]) for a in (x, y, season))
        xv, yv, sv = (torch.from_numpy(a[va]) for a in (x, y, season))
        best, best_state, stale = float("inf"), None, 0
        self.val_history: list[float] = []  # validation loss per epoch
        for _ in range(self.epochs):
            self.net.train()
            order = rng.permutation(len(xt))
            for i in range(0, len(order), 256):
                idx = torch.from_numpy(order[i : i + 256])
                opt.zero_grad()
                loss_fn(self.net(xt[idx], st[idx]), yt[idx]).backward()
                opt.step()
            self.net.eval()
            with torch.no_grad():
                val = float(loss_fn(self.net(xv, sv), yv))
            self.val_history.append(val)
            if val < best - 1e-4:
                best, stale = val, 0
                best_state = {k: t.clone() for k, t in self.net.state_dict().items()}
            else:
                stale += 1
                if stale >= self.patience:
                    break
        self.net.load_state_dict(best_state)
        self.net.eval()
        with torch.no_grad():
            self.val_loss = float(loss_fn(self.net(xv, sv), yv))  # of the restored weights
        return self

    def predict(self, anom: pd.Series, origins) -> pd.DataFrame:
        """Anomaly forecast for leads 1..horizon from each origin. An origin whose lookback
        window is short or has a missing day is skipped, never guessed."""
        rows, feats, kept = [], [], []
        for origin in origins:
            window = anom.loc[:origin].iloc[-self.lookback :]
            if len(window) < self.lookback or window.isna().any():
                continue
            if (window.index[-1] - window.index[0]).days != self.lookback - 1:
                continue
            feats.append(window.to_numpy(dtype=np.float32) / self.scale)
            kept.append(origin)
        if not kept:
            return pd.DataFrame(columns=["origin", "lead_days", "anom_pred"])
        with torch.no_grad():
            out = self.net(torch.from_numpy(np.stack(feats)), torch.from_numpy(_season(kept)))
        out = out.numpy() * self.scale
        for origin, pred in zip(kept, out, strict=True):
            rows.extend((origin, lead, float(p)) for lead, p in enumerate(pred, start=1))
        return pd.DataFrame(rows, columns=["origin", "lead_days", "anom_pred"])

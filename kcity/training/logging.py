"""Online means for one logging interval; no training tensors or history retained."""


class IntervalMean:
    def __init__(self):
        self.count = 0
        self.totals = {}

    def add(self, metrics):
        if self.count and metrics.keys() != self.totals.keys():
            raise ValueError('Metric keys changed within a logging interval')
        for key, value in metrics.items():
            self.totals[key] = self.totals.get(key, 0.0) + float(value)
        self.count += 1

    def mean(self):
        return {key: value / self.count for key, value in self.totals.items()} if self.count else None

    def reset(self):
        self.count = 0
        self.totals.clear()

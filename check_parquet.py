import pandas as pd

df = pd.read_parquet("backend/data/ohlcv/RELIANCE.parquet")

print(df.head())
print()
print(df.info())
print()
print(df.tail())

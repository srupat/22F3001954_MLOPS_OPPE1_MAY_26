import subprocess
import pandas as pd

from config import PROCESSED_DATA_DIR


def run_cmd(cmd: str):
    print(f"Running: {cmd}")
    subprocess.run(cmd, shell=True, check=True)


def main():
    df = pd.read_parquet(PROCESSED_DATA_DIR / "current" / "features.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Use a small time range for materialization demo to avoid OOM.
    # This still demonstrates Feast online materialization.
    end_time = df["timestamp"].max()
    start_time = end_time - pd.Timedelta(days=7)

    print(f"Materializing sample window:")
    print(f"Start: {start_time.isoformat()}")
    print(f"End:   {end_time.isoformat()}")

    run_cmd("cd feature_repo && feast apply")
    run_cmd(
        f'cd feature_repo && feast materialize "{start_time.isoformat()}" "{end_time.isoformat()}"'
    )


if __name__ == "__main__":
    main()

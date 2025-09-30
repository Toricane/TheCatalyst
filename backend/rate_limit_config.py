"""Configuration management for rate limiting via environment variables."""

import os
from typing import Dict, List


def load_custom_rate_limits() -> Dict[str, Dict[str, int]]:
    """Load custom rate limits from environment variables.

    Format: <MODEL_NAME>_RPM, <MODEL_NAME>_TPM, <MODEL_NAME>_RPD
    Where MODEL_NAME is the model name converted to uppercase with special chars replaced by underscores.

    Example:
        GEMINI_2_5_PRO_RPM=10
        GEMINI_2_5_PRO_TPM=500000
        GEMINI_2_5_PRO_RPD=200
    """
    custom_limits: Dict[str, Dict[str, int]] = {}

    # Scan environment for rate limit variables
    for env_var in os.environ:
        if env_var.endswith(("_RPM", "_TPM", "_RPD")):
            # Extract model name and limit type
            parts = env_var.split("_")
            if len(parts) < 2:
                continue

            limit_type = parts[-1].lower()  # rpm, tpm, rpd
            model_parts = parts[:-1]

            # Reconstruct model name (convert back from env format)
            model_name = "-".join(model_parts).lower().replace("_", ".")

            try:
                limit_value = int(os.environ[env_var])
                if model_name not in custom_limits:
                    custom_limits[model_name] = {}
                custom_limits[model_name][limit_type] = limit_value
            except ValueError:
                print(
                    f"Warning: Invalid rate limit value for {env_var}: {os.environ[env_var]}"
                )

    return custom_limits


def print_rate_limit_config(limits: Dict[str, Dict[str, int]]) -> None:
    """Print current rate limit configuration for debugging."""
    print("🔧 Current Rate Limit Configuration:")
    for model, model_limits in limits.items():
        print(f"  {model}:")
        print(f"    - Requests/minute: {model_limits.get('rpm', 'unlimited')}")
        print(f"    - Tokens/minute: {model_limits.get('tpm', 'unlimited')}")
        print(f"    - Requests/day: {model_limits.get('rpd', 'unlimited')}")


def validate_rate_limits(limits: Dict[str, Dict[str, int]]) -> List[str]:
    """Validate rate limit configuration and return any warnings."""
    warnings = []

    for model, model_limits in limits.items():
        # Check for sensible values
        rpm = model_limits.get("rpm", 0)
        tpm = model_limits.get("tpm", 0)
        rpd = model_limits.get("rpd", 0)

        if rpm and rpm < 1:
            warnings.append(f"{model}: RPM too low ({rpm})")
        if rpm and rpm > 1000:
            warnings.append(f"{model}: RPM unusually high ({rpm})")

        if tpm and tpm < 100:
            warnings.append(f"{model}: TPM too low ({tpm})")
        if tpm and tpm > 10_000_000:
            warnings.append(f"{model}: TPM unusually high ({tpm})")

        if rpd and rpd < 10:
            warnings.append(f"{model}: RPD too low ({rpd})")
        if rpd and rpd > 100_000:
            warnings.append(f"{model}: RPD unusually high ({rpd})")

        # Consistency checks
        if rpm and rpd and (rpm * 1440) > rpd:  # 1440 minutes in a day
            warnings.append(f"{model}: RPM × 1440 exceeds RPD (potential conflict)")

    return warnings


if __name__ == "__main__":
    custom = load_custom_rate_limits()
    print_rate_limit_config(custom)

    warnings = validate_rate_limits(custom)
    if warnings:
        print("\n⚠️  Configuration warnings:")
        for warning in warnings:
            print(f"  - {warning}")

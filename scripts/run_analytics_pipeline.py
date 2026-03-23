"""
Standalone runner for analytics_pipeline (without Mage runtime).
Mocks the Mage decorators and runs load → detect → export in sequence.
"""
import sys, os, types

# Resolve project root: supports Docker (/home/src) and GitHub Actions ($GITHUB_WORKSPACE)
_script_dir   = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)  # one level up from scripts/
_mage_project = os.path.join(_project_root, 'mage_project')
sys.path.insert(0, _mage_project)

# Mock Mage decorators so pipeline blocks run outside the Mage runtime
for mod_name in [
    'mage_ai', 'mage_ai.settings', 'mage_ai.settings.repo',
    'mage_ai.data_preparation', 'mage_ai.data_preparation.decorators',
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

def _noop(fn): return fn
sys.modules['mage_ai.settings.repo'].get_repo_path = lambda: _mage_project
sys.modules['mage_ai.data_preparation.decorators'].data_loader   = _noop
sys.modules['mage_ai.data_preparation.decorators'].transformer   = _noop
sys.modules['mage_ai.data_preparation.decorators'].data_exporter = _noop

# Load .env only when running locally (GitHub Actions injects secrets as env vars)
_env_file = os.path.join(_project_root, '.env')
if os.path.isfile(_env_file):
    from dotenv import load_dotenv
    load_dotenv(_env_file)

# ── Step 0: Refresh feature store in MotherDuck ──────────────────────────────
print("=" * 60)
print("STEP 0: refresh_feature_store")
print("=" * 60)
sys.path.insert(0, _script_dir)
from refresh_feature_store import refresh_feature_store
refresh_feature_store()

# ── Step 1: Load ─────────────────────────────────────────────────────────────
print("=" * 60)
print("STEP 1: load_analytics_data")
print("=" * 60)
from data_loaders.load_analytics_data import load_data
raw = load_data()
for k, v in raw.items():
    print(f"  {k}: {len(v)} rows")

# ── Step 2: Detect anomalies ─────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 2: detect_anomalies")
print("=" * 60)
from transformers.detect_anomalies import transform
insights = transform(raw)
print(f"\nTop 10 insights by severity:")
for i in insights[:10]:
    print(f"  [{i['severity']:.2f}] {i['insight_type']:18s} | {i['entity_name']:25s} | z={i['zscore']:+.2f}")

# ── Step 3: Generate + store ─────────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 3: generate_insights")
print("=" * 60)
from data_exporters.generate_insights import export_data
export_data(insights)

print("\nDone.")

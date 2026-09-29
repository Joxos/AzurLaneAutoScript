"""Check the requirements matrix against the tree, not against the plan.

docs/requirements-matrix.md claims, per row: an implementation artefact, the
gate that proves it, and whether a real machine has confirmed it. This script
re-checks the first two - a claim whose file has gone missing fails here, so
the matrix cannot quietly rot.

Run: .venv\\Scripts\\python.exe dev_tools/verify_requirements.py
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (id, matrix row, artefact path, gate path)
ROWS: list[tuple[str, str, str, str]] = [
    ("1.1", "日志框按 rich 格宽对齐", "webapp/src/lib/cells.ts", "dev_tools/verify_log_align.mjs"),
    ("1.2", "宽度表与后端同源", "webapp/src/lib/cell-widths.json", "dev_tools/gen_log_cell_widths.py"),
    ("1.3", "每条日志后的空行", "module/webui/api/helpers.py", "dev_tools/verify_log_align.mjs"),
    ("1.4", "两个日志面板同一排版", "webapp/src/styles/base.css", "webapp/src/lib/ansi.test.ts"),
    ("2.1", "统一 CLI 入口", "module/cli/app.py", "tests/test_cli.py"),
    ("2.2", "桌面窗口无黑窗", "deploy/packaging/launcher.py", "tests/test_launcher.py"),
    ("2.3", "数据目录隔离", "module/logger.py", "tests/test_launcher.py"),
    ("2.4", "NSIS 安装器", "deploy/packaging/alas_installer.nsi", ".github/workflows/release.yml"),
    ("2.5", "CI 出 setup.exe + 冒烟", ".github/workflows/release.yml", "dev_tools/verify_docker_packaging.py"),
    ("2.6", "应用内更新（分离启动）", "module/webui/updater.py", "deploy/packaging/README.md"),
    ("2.7", "Docker 含前端", "deploy/docker/Dockerfile", "dev_tools/verify_docker_packaging.py"),
    ("3.1", "托盘图标与菜单", "deploy/packaging/launcher_tray.py", "tests/test_launcher_tray.py"),
    ("3.2", "关窗口隐藏", "module/cli/run.py", "tests/test_window_tray.py"),
    ("3.3", "窗口找回端点", "module/webui/api/routers/window.py", "tests/test_window_tray.py"),
    ("4.1", "上游 SOP", "docs/upstream-sync.md", "dev_tools/verify_thresholds.py"),
    ("4.2", "识别参数漂移门", "dev_tools/verify_thresholds.py", "dev_tools/baseline/assets_snapshot.json"),
    ("4.3", "资产格式不退化", "dev_tools/dedup_assets.py", "dev_tools/baseline/assets_snapshot.json"),
    ("5.1", "flow 执行核", "module/flow/engine.py", "tests/test_flow_engine.py"),
    ("5.2", "双跑等价门", "dev_tools/flow_replay.py", "tests/test_flow_replay.py"),
    ("5.3", "首批迁移（awaken）", "module/awaken/awaken.py", "tests/test_flow_awaken.py"),
    ("5.4", "地图数据等价门", "campaign", "dev_tools/verify_map_data.py"),
]

# Rows the matrix marks as not done on purpose; listed so the script can say so
# loudly instead of letting a reader assume coverage.
KNOWN_GAPS = [
    "S5 剩余 272 处 while 未迁（本轮只做 awaken + 上游已有的 11 个文件）",
    "托盘的开机自启未实现",
    "NSIS/托盘/升级链/数据目录真机未验（见 docs/real-machine-checklist.md）",
]


def main() -> int:
    missing: list[str] = []
    for ident, row, artefact, gate in ROWS:
        artefact_path = ROOT / artefact
        gate_path = ROOT / gate
        artefact_ok = artefact_path.exists()
        gate_ok = gate_path.exists()
        if not (artefact_ok and gate_ok):
            missing.append(f"{ident} {row}: artefact={'ok' if artefact_ok else 'MISSING'} gate={'ok' if gate_ok else 'MISSING'}")
        print(f"  [{'OK  ' if artefact_ok and gate_ok else 'GAP '}] {ident:<4} {row:<28} {artefact}  <-  {gate}")
    print(f"\nREQUIREMENTS: {len(ROWS) - len(missing)}/{len(ROWS)} rows backed by an artefact and a gate")
    for line in missing:
        print(f"  MISSING {line}")
    print("\nKnown gaps (stated in docs/requirements-matrix.md, not silently absent):")
    for gap in KNOWN_GAPS:
        print(f"  - {gap}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())

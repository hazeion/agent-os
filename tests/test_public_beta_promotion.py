from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.public_beta_promotion import (
    CONFIRMATION,
    expected_public_assets,
    prepare_promotion,
    validate_cohort_summary_url,
    verify_published_release,
)
from scripts.release_rehearsal import build_bundle, expected_artifacts


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_TAG = "v0.1.0-beta.1-rc.7"
SOURCE_SHA = "a" * 40
COHORT_URL = "https://github.com/hazeion/agent-os/issues/123"


class PublicBetaPromotionTests(unittest.TestCase):
    def make_candidate(self, root: Path) -> tuple[Path, Path, Path]:
        artifact_dir = root / "artifacts"
        metadata_dir = root / "metadata"
        bundle_dir = root / "candidate-assets"
        artifact_dir.mkdir()
        bundle_dir.mkdir()
        for index, name in enumerate(expected_artifacts(), start=1):
            (artifact_dir / name).write_bytes(f"signed-artifact-{index}".encode())
        build_bundle(artifact_dir, metadata_dir, CANDIDATE_TAG, SOURCE_SHA)
        for path in artifact_dir.iterdir():
            (bundle_dir / path.name).write_bytes(path.read_bytes())
        for name in ("SHA256SUMS", "release-manifest.json"):
            (bundle_dir / name).write_bytes((metadata_dir / name).read_bytes())
        snapshot = root / "candidate-release.json"
        snapshot.write_text(json.dumps({
            "assets": [
                {
                    "digest": f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
                    "name": path.name,
                    "size": path.stat().st_size,
                }
                for path in sorted(bundle_dir.iterdir())
            ],
            "draft": False,
            "html_url": f"https://github.com/hazeion/agent-os/releases/tag/{CANDIDATE_TAG}",
            "immutable": True,
            "prerelease": True,
            "tag_name": CANDIDATE_TAG,
        }))
        cohort = root / "cohort-summary.json"
        cohort.write_text(json.dumps({
            "body": f"""### Exact tested RC tag and source commit

{CANDIDATE_TAG} at {SOURCE_SHA}

### Cohort window and coverage

Aggregate results

### Installation and first-workflow results

Aggregate results

### Migration, backup, and recovery results

Aggregate results

### Remote matrix v1 results

Aggregate results

### Issues and repeated confusion

Aggregate results

### Exit attestation

- [x] At least 10 external testers used Mentat for roughly two weeks and every Milestone 7 exit criterion passed.
- [x] No unresolved P0 or P1 issue remains.
- [x] This issue contains only aggregate, redacted, public-safe evidence.
""",
            "state": "CLOSED",
            "url": COHORT_URL,
        }))
        return bundle_dir, snapshot, cohort

    def promote(self, root: Path, **overrides):
        bundle, snapshot, cohort = self.make_candidate(root)
        values = {
            "bundle_dir": bundle,
            "release_snapshot": snapshot,
            "cohort_snapshot": cohort,
            "output_notes": root / "PUBLIC_BETA_NOTES.md",
            "candidate_tag": CANDIDATE_TAG,
            "source_sha": SOURCE_SHA,
            "cohort_summary_url": COHORT_URL,
            "confirmation": CONFIRMATION,
        }
        values.update(overrides)
        return prepare_promotion(**values), values

    def test_exact_candidate_assets_produce_public_notes_without_rebuilding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, values = self.promote(root)
            notes = values["output_notes"].read_text()
            self.assertEqual(manifest["release_tag"], CANDIDATE_TAG)
            self.assertEqual(
                {path.name for path in values["bundle_dir"].iterdir()},
                expected_public_assets(),
            )
            self.assertIn("exact tested assets", notes)
            self.assertIn("were not rebuilt or renamed", notes)
            self.assertIn(CANDIDATE_TAG, notes)
            self.assertIn(COHORT_URL, notes)
            self.assertIn("SUPPORT.md", notes)
            self.assertIn("SECURITY", notes)

    def test_candidate_inventory_manifest_checksums_and_bytes_are_exact(self):
        mutations = ("extra", "artifact", "manifest", "checksums", "wholesale")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                bundle, snapshot, cohort = self.make_candidate(root)
                if mutation == "extra":
                    (bundle / "extra.txt").write_text("extra")
                elif mutation == "artifact":
                    (bundle / next(iter(expected_artifacts()))).write_bytes(b"changed")
                elif mutation == "manifest":
                    payload = json.loads((bundle / "release-manifest.json").read_text())
                    payload["source_sha"] = "b" * 40
                    (bundle / "release-manifest.json").write_text(json.dumps(payload))
                else:
                    if mutation == "checksums":
                        (bundle / "SHA256SUMS").write_text("0" * 64 + "  wrong\n")
                    else:
                        replacement = root / "replacement"
                        metadata = root / "replacement-metadata"
                        replacement.mkdir()
                        for index, name in enumerate(expected_artifacts(), start=1):
                            (replacement / name).write_bytes(f"substituted-{index}".encode())
                        build_bundle(replacement, metadata, CANDIDATE_TAG, SOURCE_SHA)
                        for path in replacement.iterdir():
                            (bundle / path.name).write_bytes(path.read_bytes())
                        for name in ("SHA256SUMS", "release-manifest.json"):
                            (bundle / name).write_bytes((metadata / name).read_bytes())
                with self.assertRaises(ValueError):
                    prepare_promotion(
                        bundle, snapshot, cohort, root / "notes.md", CANDIDATE_TAG,
                        SOURCE_SHA, COHORT_URL, CONFIRMATION,
                    )

    def test_release_snapshot_must_be_the_exact_published_prerelease(self):
        for field, value in (
            ("draft", True),
            ("immutable", False),
            ("prerelease", False),
            ("tag_name", "wrong"),
            ("html_url", "https://example.com"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                bundle, snapshot, cohort = self.make_candidate(root)
                payload = json.loads(snapshot.read_text())
                payload[field] = value
                snapshot.write_text(json.dumps(payload))
                with self.assertRaisesRegex(ValueError, "exact immutable published release"):
                    prepare_promotion(
                        bundle, snapshot, cohort, root / "notes.md", CANDIDATE_TAG,
                        SOURCE_SHA, COHORT_URL, CONFIRMATION,
                    )

    def test_github_asset_digests_bind_candidate_and_final_release_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, snapshot, _cohort = self.make_candidate(root)
            verify_published_release(bundle, snapshot, CANDIDATE_TAG, prerelease=True)
            payload = json.loads(snapshot.read_text())
            payload["prerelease"] = False
            payload["tag_name"] = "v0.1.0-beta.1"
            payload["html_url"] = "https://github.com/hazeion/agent-os/releases/tag/v0.1.0-beta.1"
            snapshot.write_text(json.dumps(payload))
            verify_published_release(
                bundle, snapshot, "v0.1.0-beta.1", prerelease=False
            )
            payload["assets"][0]["digest"] = "sha256:" + "0" * 64
            snapshot.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "GitHub digest"):
                verify_published_release(
                    bundle, snapshot, "v0.1.0-beta.1", prerelease=False
                )

    def test_confirmation_tags_source_and_cohort_url_fail_closed(self):
        self.assertEqual(validate_cohort_summary_url(COHORT_URL), COHORT_URL)
        for bad_url in (
            "https://github.com/hazeion/agent-os/issues/0",
            "https://github.com/other/repo/issues/1",
            "https://github.com/hazeion/agent-os/issues/1?private=x",
        ):
            with self.assertRaises(ValueError):
                validate_cohort_summary_url(bad_url)
        cases = {
            "confirmation": "yes",
            "candidate_tag": "v0.1.0-beta.1",
            "source_sha": "A" * 40,
            "cohort_summary_url": "https://example.com/issues/1",
        }
        for key, value in cases.items():
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                bundle, snapshot, cohort = self.make_candidate(root)
                kwargs = {
                    "bundle_dir": bundle,
                    "release_snapshot": snapshot,
                    "cohort_snapshot": cohort,
                    "output_notes": root / "notes.md",
                    "candidate_tag": CANDIDATE_TAG,
                    "source_sha": SOURCE_SHA,
                    "cohort_summary_url": COHORT_URL,
                    "confirmation": CONFIRMATION,
                }
                kwargs[key] = value
                with self.assertRaises(ValueError):
                    prepare_promotion(**kwargs)

    def test_output_is_exclusive_and_cli_loads_outside_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, snapshot, cohort = self.make_candidate(root)
            output = root / "notes.md"
            output.write_text("existing")
            with self.assertRaises(FileExistsError):
                prepare_promotion(
                    bundle, snapshot, cohort, output, CANDIDATE_TAG, SOURCE_SHA,
                    COHORT_URL, CONFIRMATION,
                )
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "public_beta_promotion.py"), "--help"],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_cohort_snapshot_must_be_closed_bound_and_fully_attested(self):
        mutations = {
            "open": lambda payload: payload.update(state="OPEN"),
            "wrong-url": lambda payload: payload.update(url="https://github.com/hazeion/agent-os/issues/999"),
            "wrong-source": lambda payload: payload.update(body=payload["body"].replace(SOURCE_SHA, "b" * 40)),
            "unchecked": lambda payload: payload.update(body=payload["body"].replace("- [x] No unresolved", "- [ ] No unresolved")),
            "spoofed-check": lambda payload: payload.update(body=payload["body"].replace(
                "- [x] No unresolved", "- [ ] No unresolved", 1
            ).replace(
                "Aggregate results\n\n### Installation",
                "- [x] No unresolved P0 or P1 issue remains.\n\n### Installation",
                1,
            )),
            "duplicate-heading": lambda payload: payload.update(body=payload["body"] + "\n### Exit attestation\n"),
            "wrong-section": lambda payload: payload.update(body=payload["body"].replace(SOURCE_SHA, "not the source").replace("Aggregate results", SOURCE_SHA, 1)),
            "old-then-expected": lambda payload: payload.update(body=payload["body"].replace(
                f"{CANDIDATE_TAG} at {SOURCE_SHA}",
                f"v0.1.0-beta.1-rc.6 at {'b' * 40}; {CANDIDATE_TAG} at {SOURCE_SHA}",
            )),
            "expected-then-other": lambda payload: payload.update(body=payload["body"].replace(
                f"{CANDIDATE_TAG} at {SOURCE_SHA}",
                f"{CANDIDATE_TAG} at {SOURCE_SHA}; v0.1.0-beta.1-rc.8 at {'b' * 40}",
            )),
            "duplicate-identity": lambda payload: payload.update(body=payload["body"].replace(
                f"{CANDIDATE_TAG} at {SOURCE_SHA}",
                f"{CANDIDATE_TAG} at {SOURCE_SHA}\n{CANDIDATE_TAG} at {SOURCE_SHA}",
            )),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                bundle, snapshot, cohort = self.make_candidate(root)
                payload = json.loads(cohort.read_text())
                mutate(payload)
                cohort.write_text(json.dumps(payload))
                with self.assertRaises(ValueError):
                    prepare_promotion(
                        bundle, snapshot, cohort, root / "notes.md", CANDIDATE_TAG,
                        SOURCE_SHA, COHORT_URL, CONFIRMATION,
                    )

    def test_workflow_promotes_candidate_assets_without_a_rebuild(self):
        workflow = (ROOT / ".github/workflows/promote-public-beta.yml").read_text()
        signed = (ROOT / ".github/workflows/signed-release-artifacts.yml").read_text()
        self.assertIn("environment: beta-release", workflow)
        self.assertIn("github.ref_protected", workflow)
        self.assertIn("python scripts/verify_release_checks.py", workflow)
        self.assertIn("RELEASE_SOURCE_SHA: ${{ inputs.candidate_source_sha }}", workflow)
        self.assertIn("--cohort-snapshot cohort-summary.json", workflow)
        self.assertIn("gh release verify \"$CANDIDATE_TAG\"", workflow)
        self.assertIn("immutable, prerelease, tag_name", workflow)
        self.assertIn("gh release download \"$CANDIDATE_TAG\"", workflow)
        self.assertIn("python scripts/public_beta_promotion.py", workflow)
        self.assertIn("retention-days: 90", workflow)
        self.assertIn('git tag --annotate v0.1.0-beta.1 "$SOURCE_SHA"', workflow)
        self.assertIn("gh release create v0.1.0-beta.1", workflow)
        self.assertIn("verify-release", workflow)
        self.assertIn("gh release verify v0.1.0-beta.1", workflow)
        self.assertNotIn("--prerelease", workflow)
        self.assertNotIn("python -m build", workflow)
        self.assertNotIn("scripts/build_native.py", workflow)
        self.assertIn("validate-rc-tag", signed)
        self.assertIn("Verify immutable prerelease identity and attestation", signed)
        self.assertIn("gh release verify \"$RELEASE_TAG\"", signed)

    def test_publication_docs_and_exit_form_keep_external_gates_honest(self):
        guide = (ROOT / "PUBLIC_BETA_RELEASE.md").read_text()
        normalized_guide = " ".join(guide.split())
        exit_form = (ROOT / ".github/ISSUE_TEMPLATE/beta_exit_summary.yml").read_text()
        road = (ROOT / "ROAD_TO_BETA.md").read_text()
        readme = (ROOT / "README.md").read_text()
        for required in (
            "Milestone 6 is complete",
            "Milestone 7 is complete",
            "No P0 or P1 issue is open",
            "PROMOTE_V0.1.0_BETA_1",
            "GitHub release immutability is enabled",
            "asset digests and attestation",
            "recovery bundle before creating the final tag",
            "Do not create the tag by hand",
            "do not replace it or move/delete the tag",
            "at least twice a week",
        ):
            self.assertIn(required, normalized_guide)
        self.assertIn("Never include participant identities", exit_form)
        self.assertIn("At least 10 external testers", exit_form)
        self.assertIn("No unresolved P0 or P1", exit_form)
        self.assertIn("Repository preparation status", road)
        self.assertIn("Dispatch remains blocked", road)
        self.assertLess(readme.index("[Mentat releases page]"), readme.index("## Try the development build"))
        for required in ("signed `.pkg`", "signed `.exe`", "pipx install WHEEL_URL", "mentat setup", "mentat start"):
            self.assertIn(required, readme)
        self.assertIn("no final public beta yet", readme)


if __name__ == "__main__":
    unittest.main()

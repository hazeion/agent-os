"""One retained foreground, nonexecuting Linux custody qualification attempt.

Source-checkout tool only. It has no CLI main, launcher, downloader or control
interface. The separately reviewed foreground launcher must establish stdio-only
inheritance with close_fds=True and lower its own NOFILE hard/soft limits to at
most 64 before importing this module. Never invoke it in an existing app process.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

SOURCE_COMMIT = 'fc4e572b17ea9032fadae867743e6f0b05562aeb'
# Generated from that immutable Git tree, excluding tests. No supplied manifest.
SOURCE_BLOBS = (
    ('agent_console_artifacts.py', 40629, '8a38578c3ef26c8000f6a44d43f6a8e09a48d644'),
    ('agent_console_attachments.py', 66209, '28083d8caf6a6df3f09a8a91a5e4940a3fe2a97f'),
    ('agent_console_telemetry.py', 6418, '72f5538e2f09f39106d5444290af37da3dbaf737'),
    ('agent_registry.py', 38358, '624c4e94eef3645fb5500de5048eacf0403a6231'),
    ('agent_run_history.py', 16710, 'a54418cc7510e43878ac348eddf19f8bfa22fe16'),
    ('agent_runtime.py', 27673, '5919685bf5f4b9d1f9d8028255a3be50c10077a8'),
    ('agent_setup.py', 5085, 'c532dc7d0716722de79e17fe23d9cadb0f396690'),
    ('codex_runtime.py', 76048, '5d4a482bd57b90f35f1896c324eeb3d60a94974c'),
    ('codex_task_creation.py', 20534, 'c5cd9da585d267d9c215f8d0cf8ba8941ffa539b'),
    ('command_manifest.py', 2112, '3821f9121b0e3988e11d249dfda0f640fec24671'),
    ('conversation_attachments.py', 33959, '50e3048d52a8c40745602b790d767963375ef9a0'),
    ('conversation_planning.py', 41331, 'dc3c1db0370cfaa1b46b0addf154374281372d3a'),
    ('conversation_repository.py', 97188, '9619b512f334db34388eb1c919207b1a778d1f65'),
    ('data_backup_restore.py', 86682, 'add023d69fd20a3c58b3798be3b6f9331516983c'),
    ('data_documents.py', 5748, '6328fb1f440d1bceb3cb90a0fb06ea54c14fb22c'),
    ('data_layout.py', 47723, 'b35007a9fa3aa3d4d4dbb7d0d26bdd32290704b5'),
    ('data_schema.py', 54566, 'b64e533b498f736a9f0ff14269f3ac4250d3f641'),
    ('delegation_artifacts.py', 17219, 'bb63bee7556bc756a660c17b0460d96bdbeb83f3'),
    ('deploy/__init__.py', 204, '97f9130216e195ce66f6728d93c879bb1263634a'),
    ('deploy/caddy/__init__.py', 646, '822dd17d0bbdcb93f43e1c676f282b4d0bf6ce0e'),
    ('deploy/caddy/caddy-lock.json', 1993, '0df36105444a53bfcf498259dc87261ebb7a3b23'),
    ('deploy/caddy/disposable_integration.py', 34451, 'cac15e252fe71f9379ed7f6da7cafe4beb020936'),
    ('deploy/caddy/linux_harness.py', 5187, 'fd9c81ab659211275b1172f1fcfc4c0b5094da87'),
    ('deploy/caddy/owner_integration.py', 4108, 'c7d6a0e0d15d07c2e0265516071775a43008586f'),
    ('deploy/caddy/owner_profile.py', 1978, '9c46e2e07ef0494b6e2c99622ddc1aa0f5610c30'),
    ('deploy/caddy/profile.py', 19926, '7a3db8fba1fedec834ff3d3264136470220a9581'),
    ('deploy/caddy/setup_integration.py', 4606, '09bb8402e9f05707853201b316ef6808e151a2d6'),
    ('deploy/caddy/setup_profile.py', 2957, '09c1386dcee79d6fdba4491891f3b42f5478a2e4'),
    ('deploy/project-runtime-dependency-candidate.json', 5053, '02a23a32bc093ba85f751df22c58c8f21c5f550b'),
    ('deploy/project-runtime-origin-lock.json', 50641, '3cab3f5376b880e82842f58b56ce4f95fdd12103'),
    ('diagnostics_bundle.py', 5692, 'b33d9c441a030cf7d46cd1773b62e6413136b3f4'),
    ('health_checks.py', 14336, 'b3a410e906089391e02f0ad1258d8f24c7b2a353'),
    ('hermes_browser_events.py', 4735, 'c6edd4f0c70229dff1430c4a7d6c6e20c1beabd6'),
    ('hermes_event_refresh.py', 15196, 'a7592c7e3d5c680b5685d96ec7b0927302b2ebd9'),
    ('hermes_kanban.py', 35606, '9369f635ab8ab0cf2846a34a0625940acb4b2534'),
    ('hermes_local_control.py', 37142, '78eb79dba0fe2816a5afa98550d6d8c5cd2958c0'),
    ('hermes_profile_creation.py', 9556, 'd80a648bcc606db6fa30db904ca0428d77584042'),
    ('hermes_profile_deletion.py', 6680, '7252ea0ae983d991efa812c967d387956299f90c'),
    ('hermes_profile_identity.py', 17105, '1a412921693fc909576867c996afc8d1795ec708'),
    ('hermes_profiles.py', 9081, '72b65c3289d748f5d06579087dfcb2a7c936b8c4'),
    ('hermes_provider_switching.py', 9393, 'd39e144e65de3bb662355d844743f75a88c99b47'),
    ('hermes_runtime.py', 28031, 'a7db5bad2578c74fc2f065c82326dc1a97817b4f'),
    ('hermes_skills.py', 8283, '309bae611e0b51d7c2cea8be7faa6e1f5f930ad8'),
    ('hermes_stock_compatibility.py', 4091, 'f356ae1dc54c58fd56d895152eb31929cd2efb23'),
    ('hermes_transport.py', 22234, '41beff4e7320dc19b66fa4f0a9aad36bf38caef6'),
    ('hermes_webhook_health.py', 8708, '1db5b3c46d601616204a08846dad34b2705582b8'),
    ('hermes_webhook_store.py', 6421, '99ef5498146ad4a4b246db0e7f7188ac56d932ab'),
    ('hermes_webhooks.py', 6755, '6e70f23ea64d01d6ed19943460eb4286b1e0850f'),
    ('http_read_deadline.py', 6144, 'ad4a13145d17a6f22b89fe850377cdcc07fc2527'),
    ('json_store.py', 19586, 'c70dceca42a84835ffd67c3f2b7174d56debd6cf'),
    ('link_preview_cache.py', 29229, '545d19b7826bc25070e559ef023efc47bee026ef'),
    ('link_preview_image.py', 4282, '7e8f4bdefd93437ef9b06b7bf7b89f8b77b2f6c0'),
    ('link_preview_metadata.py', 8234, 'f287a7de2dc579cd764efcf6afb9e1ef43887ce1'),
    ('link_preview_policy.py', 12779, '156b254a3a899aef03b2056a59013d7218a35fed'),
    ('link_preview_service.py', 21170, 'd904d7a87ff2194b24b296148f6a2592cd2607d9'),
    ('link_preview_transport.py', 17772, 'be2e8bdab79632528c2e74a85daf1b9d61368d44'),
    ('link_preview_webp.py', 2068, '2e6cc283dac948b843cbeaca952abc9ac7e4d640'),
    ('link_preview_worker.py', 4725, '1ed992645d66d752c36e2dce4c5916e0d216c82c'),
    ('link_preview_workers.py', 14963, 'd1fc1757b3b450429b6b9985ef10877ae0c29da8'),
    ('mentat.toml', 567, 'f2a56b5d79f6fc6d7d4a3969019b7fd74096eb02'),
    ('mentat/__init__.py', 107, '39be5520b850480a6d97471d149b6cddae8fb227'),
    ('mentat/__main__.py', 49, '8f0c1d5f6315c6afe9c6e9e2833ae445325db731'),
    ('mentat/cli.py', 32758, '39ace7ca71a36452f7d7da20e79a8c5b13397b36'),
    ('mentat/local_bridge.py', 344627, '8037983fd7d9326cede953684763546dde78eea6'),
    ('mentat/native_startup_diagnostics.py', 1953, '5d45efd9da944b67994eadedc79f46a816f1c569'),
    ('mentat/owner_setup_bridge.py', 4116, 'efc75ce2a6a9fee3cef24e41b1ab31bd3418e710'),
    ('mentat/owner_setup_cli.py', 5656, '269e10e094d30e1ddab17b4394f4899afbe8e97f'),
    ('mentat/owner_setup_guard.py', 3485, 'fdc416ace4fe30c218d5ce2053a44f09841f177c'),
    ('mentat/owner_setup_runtime.py', 6979, '8e343100d0c9b48a24e581d5e78fd9ac25a4a61a'),
    ('mentat/owner_website_cli.py', 1935, 'aa83239e4742dec1028f520f3d58abbb6bc93e8c'),
    ('mentat/owner_website_runtime.py', 3228, '9e6a88303072f1d93f1e45e40c81e2dc40a41e65'),
    ('mentat/owner_website_worker.py', 736, '94b23a27de8308c4e82dcb18de355f7c9bd606df'),
    ('mentat/package_data.py', 3689, '87ef2a30e73d645ff11e97fc865d937d2555cfed'),
    ('mentat/process_identity.py', 1432, '9dd58de0584e27ede3cbc303ba0f9d28a0096422'),
    ('mentat/project_helper_byte_custody.py', 22089, '93043f246e8a18f1cfeb3dd0e7e540acf5bc5e85'),
    ('mentat/project_library_origin.py', 25303, 'f06f694eda7c12b1c273916a6f44f0d65e03e606'),
    ('mentat/project_library_origin_worker.py', 2609, 'bf7d25fb1c26c061d85aa0a4796ebbf9c83b4592'),
    ('mentat/project_library_plt.py', 14592, 'e422a9853e79d52e9ec19008b66413de58534d44'),
    ('mentat/project_namespace_evidence.py', 4116, '47c530efb105d879f5e0cb7e9827bd235907f90d'),
    ('mentat/project_output_blob.py', 9881, '800d7edf7905044d78a0df160f8f4ff08180e175'),
    ('mentat/project_research_page.py', 5710, 'ae3d38fff268b114715dde3cdbaf1d51c14e7a2b'),
    ('mentat/project_research_reader.py', 4380, '3985b77b72a5a3c1b1fd00e06f46447584e94d62'),
    ('mentat/project_research_worker.py', 3050, '1411876c4a373bbe50b809ba3ac994bcf3dc9d15'),
    ('mentat/project_runtime_dependencies.py', 21867, '11d0bc23a82ac1fb58b74d18efc5a25a99cf2698'),
    ('mentat/project_runtime_elf.py', 8397, 'deb3917d63b2a5d309e7ecceb7148fb93948176d'),
    ('mentat/project_runtime_host_trust.py', 7423, '7ddbac115a44e60508c6559be3d7b15394466070'),
    ('mentat/project_runtime_image.py', 19754, '5e974a8a306e154107f3eaf089ba5797ff123f37'),
    ('mentat/project_runtime_image_probe.py', 4150, '24228e4c23870d86253a866f0065fdc92d3e7a05'),
    ('mentat/project_runtime_libraries.py', 14109, '4a6090d36b9f45fd8cff606c0feb1d03a77fa3f2'),
    ('mentat/project_runtime_mount_bootstrap.py', 1335, '5884fc8b4817f8105e440d64ab1cd0f2b489a535'),
    ('mentat/project_runtime_origin.py', 25251, '63954ffc719155cdfad9c3863755f6430ba925c7'),
    ('mentat/project_scope_evidence.py', 3527, '9d8995030f33fd17cfb6b16ff24a3ced6c4b126d'),
    ('mentat/project_scope_inspector.py', 4606, 'b9f2b34fb1d5ccbe4524b8e89fe61547c8332b6f'),
    ('mentat/project_scope_readback.py', 10500, '33bf8dafd8208c911a6c0eba17cbd27bb6d6f004'),
    ('mentat/project_scope_readback_worker.py', 3095, 'ac22c85ec60a559d2fc9f6c108da09a2052448b2'),
    ('mentat/project_system_origin.py', 22285, '2126f2c921b64dd172ccf2990de3f94053a26079'),
    ('mentat/project_system_origin_worker.py', 2694, '37715a755ae38ce2e5c503554fee250c671c012b'),
    ('mentat/project_worker_bootstrap.py', 3237, '4201b382abe4ad62190ca5ce399c4d012fbab78a'),
    ('mentat/project_worker_frontend.py', 16884, '2e77b830b17b366854920b5baf94da393da30bee'),
    ('mentat/project_worker_namespace.py', 21206, '6ff8b590c5121d60634eb8b62736bcdbf99ad827'),
    ('mentat/project_worker_scope.py', 24010, '037cca512170687a02c11ee5bfabbe9feab67a33'),
    ('mentat/version.py', 125, '1351babf95089fc0860a9bc465af7f0689f04f1d'),
    ('mentat/web_runtime.py', 24178, 'e65b800e30b6a82705e1b662261e3f5709e5b54c'),
    ('mentat_db.py', 178390, 'deed0ca8b86f59b4cc620b261b69f28da1184d6b'),
    ('mentat_lifecycle.py', 28237, 'f6d61d7d3cecabbf865c386c5eb975b8fd8cbbd8'),
    ('orchestration_service.py', 102744, '8218ee3df4f7032fdba6371b5ee480e83f1c54a1'),
    ('owner_auth.py', 72164, 'f321bec3ca61a4b083001e98b3e5c622cfe51943'),
    ('owner_auth_google.py', 10410, '6ae892f2d65f4ea385484eb4c2628e7cb362a81b'),
    ('owner_auth_google_transactions.py', 12115, 'fecaf94a38fdad1d81187a318e8c619adb24eb57'),
    ('owner_auth_google_transport.py', 11737, '74b85e643bfa80e171b749793e1f63cf30ec32ed'),
    ('owner_auth_google_worker.py', 5471, '4046f0ee08bb8e51fc83214a4ce4d1b9faa70d02'),
    ('owner_auth_setup.py', 15633, '9821171d32e754cc31ff47d9b02ab2d6bde281a6'),
    ('owner_auth_webauthn.py', 9427, '4ab762f9be2144174f4865e840c5f960a7e51d14'),
    ('owner_gateway.py', 4647, 'fda706765d5648d6d29f093657d55b5da0128d32'),
    ('owner_inbox.py', 34912, 'e32ec3ffcad788e1981c7b2c4fbb5a92a6b49c58'),
    ('owner_inbox_http.py', 4504, '85a2e4a104718f33714455e65515f61898694183'),
    ('packaging/mentat_native.py', 2668, '45641455db8d9895eb23f902efcf43478f2cdcad'),
    ('planning_calendar.py', 16116, '16834078843175b43e5ebdbf59ea0b0af2f263dc'),
    ('planning_deletion.py', 34912, 'b62aebcadef67d936a514fad166567157404f89f'),
    ('private_console_unit.py', 71111, 'bb6cc21b053585ecb0c7fe370070a26d027057bb'),
    ('private_state.py', 17951, 'efd18c8b45cde440012365107c142c9ca526491a'),
    ('project_context.py', 22337, '59c91c2c5f635f2f7271b89ef5718d391fa2121a'),
    ('project_context_access.py', 12515, '5a7543434e18ebbf568e2b6af78ddec0889a61a6'),
    ('project_context_editor.py', 18061, 'e041b406b5e9e31c2fca31e416952f297df52c2c'),
    ('project_context_http.py', 6662, '816cef56756e20be16dc21db2c2bbc8b7f892a8c'),
    ('project_deliverable_review.py', 16454, 'c953ef1b6246f34f059c0a16578202942301fc39'),
    ('project_deliverables.py', 37257, '1c39ddf25b6385db8dc12b89903b8b3e24d107fa'),
    ('project_deliverables_http.py', 7556, 'cc7bfd344cbae069d25c0cabd5f60e9bd1c95103'),
    ('project_inference_broker.py', 21629, 'f2ff68b4719e40e1731fab8ba46280eee78b2db2'),
    ('project_leads.py', 16299, '9fa30d895865ca03141c33962c060c341189e319'),
    ('project_leads_http.py', 3313, '14f7e90b1827f3479300de26f27c9338fc0382b2'),
    ('project_output_reservations.py', 6457, '3a4610de22f89335f46fec44c2c3277b3c266585'),
    ('project_plan_policy.py', 7837, 'cbbba7fe2089ec4d25d779d5a6c6a7c34f3322ed'),
    ('project_planning_inputs.py', 29502, 'b3147417ca49bbc0ce1805647d4d2a158f959659'),
    ('project_planning_inputs_http.py', 4115, 'd0f4e3b5ef970d422ce92f137afa2864097ecc2e'),
    ('project_plans.py', 32892, '0d8bcfe79e1f192ab64329f211c668ca7b009f37'),
    ('project_plans_http.py', 4238, 'b727f3247d3dab94efb674aafdbaa8ab5bafc3c7'),
    ('project_producers.py', 44502, 'bcc5c548c053f73ede3b5fa561aff6cee14a3821'),
    ('project_proposal_artifact.py', 6059, '7164fa35f5d6699618a4b60be28528c7d5e5c1e4'),
    ('project_proposal_input_receipts.py', 8114, '3ab8991cc0651231342f0563d1c0874e961f93d2'),
    ('project_repository.py', 31894, 'ba089a1978fa0e9d76d51641cd765bdc4ffab1f7'),
    ('project_scope_journal.py', 12001, 'a9b44173ef6ba50963010ace01f9fd230ee94e88'),
    ('project_worker_journal.py', 23426, '1325d80baf5a30b7a6b448dd564681ef4e8e57b9'),
    ('pyproject.toml', 3750, '68e1084d0f250fa48c7f5799aacc8724d8454244'),
    ('remote_hermes.py', 255103, 'cbfb8d1975c2ce27425a29c8a230673309788c2b'),
    ('run_attention.py', 8313, 'b21f69f782535d6b438f36aba2445748d31c0df3'),
    ('run_input_receipts.py', 6929, 'fef0857eefdf9fe004143d276ebe8b9e925ec6cd'),
    ('run_repository.py', 355040, '865cffdb7b286e11fc7c66ad296e4181eac321b7'),
    ('runtime_config.py', 19263, 'b41921eab014e16114f0042a5b76897af49fe8fb'),
    ('scripts/agent_heartbeat.py', 10525, 'c2918d759f0c8599307e46fba900ca12d4751470'),
    ('scripts/apple_notarization.py', 9982, '8bc7a1be0279bc8f946e051509e23c92964c29d8'),
    ('scripts/archive_native_windows.py', 7695, 'bb094e1fdb0ed234e61904755df04916abce133b'),
    ('scripts/build_native.py', 5096, 'e3de74c16e1edac09875f0610e31f0c37c0b944c'),
    ('scripts/check_tracked_secrets.py', 2211, '617b442d1c67a3939e5dc4b911aa488cd20c3457'),
    ('scripts/hermes_webhook_live_validation.py', 40260, '893fb237d235e07458ccd9daf1f55d4335977325'),
    ('scripts/mentat_acceptance.py', 31737, 'd52a262cbc9ed56d500fd7971eef3e70b8c63222'),
    ('scripts/mentat_setup.py', 30326, 'a4dc6fa2939bfa61a1c61f6c99fb5469223c5b9e'),
    ('scripts/mentat_web_preview.py', 8405, '93aa9b24581f6729af698ecdda60c396fd6cc7ad'),
    ('scripts/public_beta_promotion.py', 15489, '3c6a1004cf1d17a7de20394cbf8599b1c8bf998c'),
    ('scripts/release_rehearsal.py', 9555, 'ab42c37dbdd65bda06cc83f333b1239afdc1b74c'),
    ('scripts/run_unittest_shards.py', 17562, '9432d2dc3442e3035652c6ffb43220648fc1a001'),
    ('scripts/stage_web_runtime.py', 1057, '2892adbaccf58e5c0e1212efcb0683e3a6c9bb1e'),
    ('scripts/validate_hermes_native_events.py', 6521, 'f9331e7ffa9a9a239c09f5646a7687b401802a97'),
    ('scripts/validate_hermes_stock_compatibility.py', 4232, '62d270670fae7d221790e7b6ae5339d91babf2d6'),
    ('scripts/verify_macos_architecture.py', 5231, '178ea48c4a9df5a1ea4451c296fa078c79a6f02b'),
    ('scripts/verify_python_artifacts.py', 11322, 'bb6d5a728a9ae4c19411bb4680b4ee8710d201d0'),
    ('scripts/verify_release_checks.py', 3035, '99b7e623b887b3e4b3c4c6c49fee94a200d1cba1'),
    ('scripts/verify_web_preview_lifecycle.py', 5925, '2280ca4d06184afcd1a7c0ffd5f82779975878f4'),
    ('server.py', 727741, '3c260418baecd58e468947c6246e8cef99fded45'),
    ('setup.py', 342, '7d2bf1fcb20477d623a105c8f7c4591babe849ad'),
    ('task_delegation_receipts.py', 23683, 'af194a2723f87803273016f703bc63019ad2bac9'),
    ('task_inputs.py', 29625, '4ead01761971f799f77f9145139873f024bb5299'),
    ('task_inputs_http.py', 4590, '48232e297d7191f204980e3c0ffa377970c146c0'),
    ('task_planning.py', 22751, '8077d515ab92adb6145ce1dc752178a114220524'),
    ('task_repository.py', 73283, '36ab8e77903a3e5aca27fa5d01f0d09f3298287f'),
    ('vercel_connections.py', 34859, '1937aaec681ab6e3f407da1134082de1c8580b50'),
    ('vercel_infrastructure.py', 29874, 'c2e9e06f5c854e5352b8bcd83c7b9e2a6f983713'),
    ('vercel_runtime.py', 18146, 'd9d1dea2709e29069a40fc23f8718842b97a29e0'),
)
active_attempt = None


class QualificationRefused(Exception):
    """Fixed refusal. Never include a path or underlying exception in a report."""


def _require(condition):
    if not condition:
        raise QualificationRefused()


def _identity(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid,
            value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _slot(fd):
    import fcntl
    try:
        value = os.fstat(fd)
    except OSError as error:
        if error.errno == errno.EBADF:
            return None
        raise
    return (value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode),
            fcntl.fcntl(fd, fcntl.F_GETFD))


def _inventory():
    return {fd: value for fd in range(64) if (value := _slot(fd)) is not None}


class QualificationAttempt:
    """Strongly owns every original error/lease until the foreground session ends."""

    def __init__(self, root):
        self.started = time.monotonic()  # Before the first host/source observation.
        self.deadline = self.started + 30
        self.root = root
        self.used = False
        self.lease = None
        self.errors = []
        self.uncertain_resources = []
        self.acquisition_started = False
        self.acquisition_returned = False
        self.duplicate = None
        self.former_slots = ()
        self.baseline = None
        self.report = None
        self.accepted_at = None
        self.public_member_digest = None
        self.public_input_digest = None
        self.source_root = Path(__file__).absolute().parents[1]

    def _time(self):
        _require(time.monotonic() < self.deadline)

    def _read_file(self, path, *, private=False, expected_size=None):
        """Pin every lexical ancestor while opening and reading one fixed file."""
        owners = []
        try:
            parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            owners.append([parent, Path('/'), None])
            owners[-1][2] = os.fstat(parent)
            prefix = Path('/')
            for name in path.parts[1:-1]:
                self._time()
                prefix = prefix / name
                parent = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                                 | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
                owners.append([parent, prefix, None])
                owners[-1][2] = os.fstat(parent)
            return self._read_pinned_file(path, parent, private=private,
                                          expected_size=expected_size)
        finally:
            failure = None
            for fd, lexical, before in reversed(owners):
                try:
                    after = os.fstat(fd)
                    current = lexical.lstat()
                    _require(stat.S_ISDIR(current.st_mode)
                             and (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
                             == (current.st_dev, current.st_ino))
                except BaseException as error:
                    self.errors.append(error)
                    failure = error
                try:
                    os.close(fd)
                except BaseException as error:
                    self.uncertain_resources.append(('directory-close', fd, error))
                    failure = error
            if failure is not None:
                raise QualificationRefused() from failure

    def _read_pinned_file(self, path, parent, *, private=False, expected_size=None):
        self._time()
        lexical = path.lstat()
        _require(stat.S_ISREG(lexical.st_mode) and lexical.st_nlink == 1
                 and not getattr(lexical, 'st_file_attributes', 0) & 0x400
                 and 0 <= lexical.st_size <= 16 * 1024 * 1024)
        if private:
            _require(lexical.st_uid == os.getuid() and stat.S_IMODE(lexical.st_mode) == 0o600)
        else:
            _require(not stat.S_IMODE(lexical.st_mode) & 0o222)
        if expected_size is not None:
            _require(lexical.st_size == expected_size)
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        try:
            _require(_identity(os.fstat(fd)) == _identity(lexical))
            chunks = []
            left = lexical.st_size + 1
            while left:
                self._time()
                part = os.read(fd, min(left, 1024 * 1024))
                if not part:
                    break
                chunks.append(part)
                left -= len(part)
            raw = b''.join(chunks)
            _require(len(raw) == lexical.st_size)
            _require(_identity(os.fstat(fd)) == _identity(lexical)
                     and _identity(path.lstat()) == _identity(lexical))
            self._time()
            return raw, _identity(lexical)
        finally:
            # A failed close is never retried by numeric descriptor.
            try:
                os.close(fd)
            except BaseException as error:
                self.uncertain_resources.append(('read-close', fd, error))
                raise

    def _source_layout(self):
        from importlib.machinery import EXTENSION_SUFFIXES
        python_paths = [self.source_root / name for name, _size, _blob in SOURCE_BLOBS
                        if name.endswith('.py')]
        parents = sorted({path.parent for path in python_paths})
        layout = []
        for parent in parents:
            self._time()
            value = parent.lstat()
            _require(stat.S_ISDIR(value.st_mode) and not stat.S_IMODE(value.st_mode) & 0o222
                     and not getattr(value, 'st_file_attributes', 0) & 0x400)
            layout.append((str(parent.relative_to(self.source_root)), _identity(value)))
        forbidden = {parent / '__pycache__' for parent in parents}
        for path in python_paths:
            forbidden.update(path.with_suffix(suffix) for suffix in ('.pyc', '.pyo'))
            forbidden.update(path.with_name(path.stem + suffix) for suffix in EXTENSION_SUFFIXES)
            if path.name == '__init__.py':
                forbidden.update(path.parent.with_name(path.parent.name + suffix)
                                 for suffix in EXTENSION_SUFFIXES)
        for path in sorted(forbidden):
            self._time()
            try:
                path.lstat()
            except FileNotFoundError:
                continue
            raise QualificationRefused()
        return tuple(layout)

    def _sources(self):
        layout = self._source_layout()
        manifest = []
        total = 0
        for relative, size, blob in SOURCE_BLOBS:
            raw, identity = self._read_file(self.source_root / relative, expected_size=size)
            total += len(raw)
            _require(total <= 80 * 1024 * 1024)
            digest = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            _require(digest == blob)
            manifest.append((relative, identity))
        _require(len(manifest) == len(SOURCE_BLOBS) and bool(manifest))
        _require(self._source_layout() == layout)
        return layout, tuple(manifest)

    def _inputs(self, library):
        self._time()
        _require(type(self.root) is Path or isinstance(self.root, Path))
        _require(self.root.is_absolute() and len(str(self.root).encode()) <= 1024)
        root = self.root.lstat()
        _require(stat.S_ISDIR(root.st_mode) and root.st_uid == os.getuid()
                 and stat.S_IMODE(root.st_mode) == 0o700
                 and not getattr(root, 'st_file_attributes', 0) & 0x400)
        expected = library._expected_inputs()
        names = set()
        entries = os.scandir(self.root)
        try:
            for entry in entries:
                _require(len(names) < 19 and entry.name not in names)
                names.add(entry.name)
        finally:
            try:
                entries.close()
            except BaseException as error:
                self.uncertain_resources.append(('input-enumerator-close', entries, error))
                raise
        _require(len(expected) == 19 and names == set(expected))
        manifest = []
        total = 0
        for name, (size, digest) in sorted(expected.items()):
            raw, identity = self._read_file(self.root / name, private=True, expected_size=size)
            total += len(raw)
            _require(total <= library.MAX_INPUT_BYTES and hashlib.sha256(raw).hexdigest() == digest)
            manifest.append((name, identity))
        _require(_identity(self.root.lstat()) == _identity(root))
        self._time()
        return _identity(root), tuple(manifest)

    def _inspect(self, custody, library, origin):
        import fcntl
        lease = self.lease
        _require(type(lease) is custody.FixedByteCustody)
        members = lease.members
        aliases = lease.aliases
        _require(type(members) is tuple and len(members) == 17
                 and type(aliases) is tuple and len(aliases) == 10)
        descriptors = lease._descriptors
        _require(type(descriptors) is dict and set(descriptors) == set(custody._CLASSES))
        _require([row[0] for row in members] == sorted(custody._CLASSES))
        _require(sum(row[3] == 'signed-library-archive' for row in members) == 13
                 and sum(row[3] == 'compiled-helper-pin' for row in members) == 4)
        helpers = {'/' + pin.member: (pin.member_size, pin.member_digest) for pin in origin.PINS}
        identities = set()
        slots = []
        for row in members:
            self._time()
            _require(type(row) is tuple and len(row) == 4)
            path, size, digest, trust_class = row
            _require(trust_class == custody._CLASSES[path] and type(size) is int
                     and 1 <= size <= 16 * 1024 * 1024
                     and type(digest) is str and len(digest) == 64
                     and all(c in '0123456789abcdef' for c in digest))
            if path in helpers:
                _require((size, digest) == helpers[path])
            if path in library.plt._PROFILES:
                profile = library.plt._PROFILES[path]
                _require((size, digest) == (profile.size, profile.digest))
            fd, fd_size = descriptors[path]
            _require(type(fd) is int and 3 <= fd < 64 and fd_size == size)
            details = os.fstat(fd)
            identity = details.st_dev, details.st_ino
            _require(stat.S_ISREG(details.st_mode) and details.st_size == size
                     and identity not in identities and fd not in slots
                     and fcntl.fcntl(fd, 1034) & 15 == 15
                     and fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC)
            identities.add(identity)
            slots.append(fd)
            raw = lease.read(path)
            self._time()
            _require(len(raw) == size and hashlib.sha256(raw).hexdigest() == digest)
        self.former_slots = tuple(slots)
        self.public_member_digest = hashlib.sha256(json.dumps(members, separators=(',', ':')).encode()).hexdigest()
        _require(_inventory() == self.baseline | {fd: _slot(fd) for fd in slots})
        names = set()
        for row in aliases:
            _require(type(row) is tuple and len(row) == 2)
            name, target = row
            _require(type(name) is str and type(target) is str
                     and name not in names and name not in descriptors)
            library._library_path(target, origin_path=name)
            names.add(name)
        _require(list(aliases) == sorted(aliases))
        links = dict(aliases)
        for name in links:
            current, seen = name, set()
            while current in links:
                _require(current not in seen and len(seen) < 10)
                seen.add(current)
                current = library._library_path(links[current], origin_path=current)
            _require(current in descriptors)
        path = '/' + origin.PINS[0].member  # Fixed bwrap, no caller selector.
        _require(origin.PINS[0].member == 'usr/bin/bwrap')
        fd = descriptors[path][0]
        old_offset = os.lseek(fd, 0, os.SEEK_CUR)
        self.duplicate = fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 3)
        _require(3 <= self.duplicate < 64)
        try:
            os.lseek(self.duplicate, 1, os.SEEK_SET)
            raw = lease.read(path)
            self._time()
            _require(hashlib.sha256(raw).hexdigest() == helpers[path][1]
                     and os.lseek(self.duplicate, 0, os.SEEK_CUR) == 1)
        finally:
            os.lseek(self.duplicate, old_offset, os.SEEK_SET)

    def _close(self):
        if self.duplicate is not None:
            fd, self.duplicate = self.duplicate, None
            try:
                os.close(fd)
            except BaseException as error:
                self.uncertain_resources.append(('duplicate-close', fd, error))
        if self.lease is not None:
            try:
                self.lease.close()
            except BaseException as error:
                self.uncertain_resources.append(('lease-close', self.lease, error))
        # No intervening opens before checking the former numeric slots.
        for fd in self.former_slots:
            try:
                if _slot(fd) is not None:
                    self.uncertain_resources.append(('live-former-slot', fd))
            except BaseException as error:
                self.uncertain_resources.append(('former-slot-check', fd, error))
        if self.baseline is not None:
            try:
                _require(_inventory() == self.baseline)
            except BaseException as error:
                self.uncertain_resources.append(('inventory', error))

    def run(self):
        _require(not self.used)
        self.used = True
        success = False
        try:
            self._time()
            _require(sys.platform == 'linux' and os.getuid() > 0
                     and os.getuid() == os.geteuid() and os.getgid() == os.getegid())
            import resource
            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            _require(0 < soft <= hard <= 64 and sys.dont_write_bytecode)
            source_manifest = self._sources()
            # An isolated session must not have imported project code before pinning.
            project_names = {Path(name).stem for name, _size, _blob in SOURCE_BLOBS
                             if '/' not in name and name.endswith('.py')}
            _require(not any(name == 'mentat' or name.startswith('mentat.')
                             or name in project_names for name in sys.modules))
            from mentat import project_helper_byte_custody as custody
            from mentat import project_library_origin as library
            from mentat import project_system_origin as origin
            _require(custody._supported())
            input_manifest = self._inputs(library)
            self.public_input_digest = hashlib.sha256(json.dumps(sorted(library._expected_inputs().items()), separators=(',', ':')).encode()).hexdigest()
            self.baseline = _inventory()
            _require(set(self.baseline) == {0, 1, 2})
            self._time()
            self.acquisition_started = True
            self.lease = custody.acquire_fixed_helper_bytes(self.root)
            self.acquisition_returned = True
            self._time()
            self._inspect(custody, library, origin)
            success = True
        except BaseException as error:
            self.errors.append(error)  # Keep traceback, cause, owners and pidfds alive.
        finally:
            self._close()
        try:
            if success and not self.uncertain_resources:
                _require(self._sources() == source_manifest)
                _require(self._inputs(library) == input_manifest)
                self._time()
            else:
                success = False
        except BaseException as error:
            self.errors.append(error)
            success = False
        # Failed acquisition may retain worker ownership even with baseline FDs.
        blocked = bool(self.uncertain_resources or
                       self.acquisition_started and not self.acquisition_returned)
        success = success and not blocked and not self.errors
        result = {'qualification': success, 'cleanup_verified': not blocked,
                  'owner_retained': blocked, 'session_must_remain_open': blocked,
                  'source_commit': SOURCE_COMMIT,
                  'public_input_digest': self.public_input_digest,
                  'public_member_digest': self.public_member_digest,
                  'members': 17 if success else 0, 'aliases': 10 if success else 0,
                  'signed_library_members': 13 if success else 0,
                  'compiled_helper_members': 4 if success else 0,
                  'execution_qualified': False, 'freshness_qualified': False,
                  'hostile_cases_qualified': False,
                  'elapsed_ms': max(0, int((time.monotonic() - self.started) * 1000))}
        encoded = json.dumps(result, sort_keys=True, separators=(',', ':')).encode()
        _require(len(encoded) <= 16 * 1024)
        self.accepted_at = time.monotonic()
        if success and self.accepted_at >= self.deadline:
            result['qualification'] = False
            encoded = json.dumps(result, sort_keys=True, separators=(',', ':')).encode()
        self.report = encoded
        return encoded


def begin(input_root):
    """Call once at the retained foreground prompt; keep that session open if blocked."""
    global active_attempt
    _require(active_attempt is None)
    active_attempt = QualificationAttempt(input_root)
    return active_attempt.run()


if __name__ == '__main__':
    raise SystemExit('This tool requires the reviewed retained foreground session.')

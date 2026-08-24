# Frozen source manifest

The public guide was authored from repository base commit `d963ae5e03aab49fa38a827ce86a71063d958d7d` plus the release-worktree edits listed below. SHA-256 values freeze the release-candidate source state used by the guide and narrated explainer.

| Source                                                       | SHA-256                                                            | Used for                                         |
| ------------------------------------------------------------ | ------------------------------------------------------------------ | ------------------------------------------------ |
| `README.md`                                                  | `90c11d8f0a002c9962555236371247ed1d82ce7d1a3eb6a8590ceccfee1eb5a3` | Product scope, quick starts, hosting boundary    |
| `SECURITY.md`                                                | `8e5ca0d3be9133205e3bc14f1dcfc2e78cd161a1328ba7df9f590561946d099d` | Threat model and safety language                 |
| `deploy/README.md`                                           | `3b08166040338928121ab536fec3149d3d923295337ac9fdfa77ed6e99d4608d` | Deployment paths                                 |
| `docs/source/lekiwi_v061_cutover.md`                         | `b20716725633d1611399e58724d5980050c5f6719360ba2888442abcb0a3de42` | Operator runbook                                 |
| `src/lerobot/robots/lekiwi/diagnostics.py`                   | `00a19fb08b4d08d47a8e83c804c7ac538b4457ced3d5976ea5a643ae27da5dd5` | Autodetection, profiles, battery estimation, API |
| `src/lerobot/robots/lekiwi/live_diagnostics.py`              | `0f7c3bf9f7e8acda11c119b3f1c4501407306c80a167ef05573e38b257595cdb` | Cached telemetry, bus leases, control bridge     |
| `src/lerobot/robots/lekiwi/lekiwi_host.py`                   | `8dea8d682a8d70fca5c088bb0a34cd039f8682b637c771fe06515aace8b86c8c` | Pi owner loop and network transport              |
| `src/lerobot/robots/lekiwi/static/lekiwi_diagnostics.js`     | `3ed80bcb55390cb55719b91befd05b70a43b28987781550491e0810c90c9d159` | Dashboard behavior                               |
| `src/lerobot/robots/lekiwi/static/lekiwi_3d.js`              | `28deaa9f7e7e37f6a97e96e9bcdc81b8154157fbc254d09dd31d7435945e4981` | Digital twin mapping                             |
| `src/lerobot/robots/lekiwi/static/models/lekiwi/LeKiwi.urdf` | `36e102375e1e6ffdc1ca2d343c7406284b3cabc77ae16bfc001a3da89fddc6e1` | Robot geometry and joints                        |
| `examples/lekiwi/teleoperate.py`                             | `b9938fc4a6feef26ecc215e988024c558e20b45d4e95c5bf1aaca350e343149e` | Leader loop and aggregate dashboard              |
| `ios/LeKiwiController/README.md`                             | `a65ea0a131c2da4f24518539bd05f01edfd21717cac4e926a9ab435d96f65828` | Native controller contract                       |
| `cloudflare/lekiwi-mobile-auth/src/index.ts`                 | `942482307fed1e4953def222eb84b116982b9e56f757e3a7a38adf5fabff5853` | Native Access callback                           |
| `videos/lekiwi-system-explained/SCRIPT.md`                   | `fd8ad48c3039c20f10277e9a570a793407daf3b53d5e7655948b9aec57eecf32` | Narration and factual sequence                   |
| `videos/lekiwi-system-explained/STORYBOARD.md`               | `956d5fa519582ca4bc9c1dbca01d8e96d3c44b06a6b67cb3d04893ac74ab6640` | Visual and motion plan                           |
| `videos/lekiwi-system-explained/index.html`                  | `ccca78aa0fbac7ed366172213529d586b2f728925cb13d637fd71dce27ff9461` | Checked HTML composition                         |

External platform statements were checked against Cloudflare's official Tunnel, Access self-hosted application, locally managed configuration, and Workers Static Assets documentation on 2026-08-23. External documentation is guidance, not evidence of the repository's runtime behavior.

The web-native composition is self-hosted under `site/videos/player/` and its editable project bundle is published at `https://www.hyperframes.dev/p/3b6e8464-0cf2-46c3-9450-28bda810ebd2`. The complete authoring source, narration timing, and generated assets remain in this repository.

No AI-generated factual claims about motor registers, control timing, or safety behavior were used without a repository source above.

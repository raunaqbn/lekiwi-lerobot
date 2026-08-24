# Third-party notices

This repository retains upstream history and license material. The root Apache-2.0 license covers original contributions unless a file or directory says otherwise.

| Component         | Location                                              | License                   | Source                                         |
| ----------------- | ----------------------------------------------------- | ------------------------- | ---------------------------------------------- |
| LeRobot           | Most of the repository                                | Apache-2.0                | https://github.com/huggingface/lerobot         |
| Three.js          | `src/lerobot/robots/lekiwi/static/vendor/three`       | MIT                       | https://github.com/mrdoob/three.js             |
| URDF Loader       | `src/lerobot/robots/lekiwi/static/vendor/urdf-loader` | Apache-2.0                | https://github.com/gkjohnson/urdf-loaders      |
| LeKiwi CAD export | `src/lerobot/robots/lekiwi/static/models/lekiwi`      | Apache-2.0                | Included with its source license and joint map |
| Hanken Grotesk    | `videos/lekiwi-system-explained/capture/assets/fonts` | SIL Open Font License 1.1 | https://github.com/marcologous/HankenGrotesk   |
| Newsreader        | `videos/lekiwi-system-explained/capture/assets/fonts` | SIL Open Font License 1.1 | https://github.com/productiontype/Newsreader   |

Exact license texts are stored in [`LICENSE`](./LICENSE), the Three.js [`LICENSE`](./src/lerobot/robots/lekiwi/static/vendor/three/LICENSE), the CAD export [`LICENSE.txt`](./src/lerobot/robots/lekiwi/static/models/lekiwi/LICENSE.txt), and the video font license files beside the font assets. Package metadata for URDF Loader records Apache-2.0.

The narration, music bed, and interface sound effects in the LeKiwi explainer were generated for this project and are distributed with the project under Apache-2.0.

Dependency packages installed from Python or npm registries remain under their own licenses. `uv.lock` and the Worker `package-lock.json` are dependency manifests, not relicensing statements.

If an attribution appears incomplete, open a normal issue. If it reveals a security concern or leaked credential, use the private process in [`SECURITY.md`](./SECURITY.md).

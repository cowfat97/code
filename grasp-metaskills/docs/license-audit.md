# License and revision audit

Audit date: 2026-10-21. Both repositories were actually obtained with Git.

| Repository | Pinned implementation revision | License inspected |
|---|---|---|
| luyu020816-droid/skill-dag | e8eaf48522950a9148cb30b9672e1aeca0ba82e6 | skill-dag/LICENSE: standard MIT, copyright 2026 grasp-release contributors |
| Dicklesworthstone/meta_skill | dcd3fb55cabb438dc200f9b7c784ca14c08135ce | LICENSE: standard MIT, copyright 2026 Jeffrey Emanuel |

The initial current-revision check found an additional restrictive rider. That
revision was not analyzed or ported. Git license history then located the commit
adding that rider: `707002f4d197315024f8474135538740db3726d7`. Its parent is the
historical MetaSkills revision pinned above. The complete parent tree was checked
out separately; all MetaSkills implementation analysis, extracted tests and Python
ports use only that tree. The later license does not form the license of the
historical files used here. This project makes no assertion of compatibility with
later MetaSkills code or permission to use it.

Primary evidence:
[historical MIT grant](https://github.com/Dicklesworthstone/meta_skill/blob/dcd3fb55cabb438dc200f9b7c784ca14c08135ce/LICENSE),
[license-changing commit](https://github.com/Dicklesworthstone/meta_skill/commit/707002f4d197315024f8474135538740db3726d7),
[GraSP MIT grant](https://github.com/luyu020816-droid/skill-dag/blob/e8eaf48522950a9148cb30b9672e1aeca0ba82e6/skill-dag/LICENSE).

Both grants permit modified redistribution with copyright/license retention.
Original texts are shipped under `licenses/`; NOTICE identifies authors, versions,
source URLs and modifications. The Python package is MIT. Mature dependencies have
their own licenses; no upstream model weights/assets or bundled third-party source
are redistributed. The auxiliary repositories were not used as substitute evidence.

The earlier project notes described a blanket MetaSkills blocker. Those notes were
superseded by the verified historical MIT route; no later restricted implementation
was used to fill gaps. Missing historical capabilities remain explicit limitations.

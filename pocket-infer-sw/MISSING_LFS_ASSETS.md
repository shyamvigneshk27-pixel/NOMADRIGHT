# Missing large deployment/font assets

The following files existed in the source repo as Git LFS pointers, but their
actual binary content was never downloaded to the machine this snapshot was
taken from — only the small LFS pointer text was present locally, and
pushing that pointer text (without the real object) is rejected by GitHub.
They've been removed from this repo rather than pushed as broken stubs:

**Deployment/provisioning binaries** (`rootfs/roles/...`):
- `initial/files/cuda-keyring_1.1-1_all.deb`
- `indic/files/flite_voices.zip`
- `indic/files/ctranslate2-4.6.3-cp310-cp310-linux_aarch64.whl`
- `indic/files/ctranslate2-0.1.1-Linux.deb`
- `indic/files/bhashini_models.zip`
- `indic/files/nmt_trans.zip`
- `indic/files/ASR-Hindi-CPUquantized.zip`
- `app/files/fiszizbl3rvliqpidq0nzbwz5eyi208s.whl`

**Touchscreen UI fonts** (`ioexpander/`):
- `NotoSansDevanagari-Regular-16.pcf`
- `NotoSansDevanagari-Regular-12.pcf`
- `NotoSansDevanagari-Regular-14.pcf`
- `forkawesome-16.pcf`

To restore them, pull the real objects from the original repo (which does
have them in LFS storage) with `git lfs pull` there, then copy them into the
matching paths here.

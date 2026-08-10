# H5 Viewer — execution plan

Updated: 2026-08-10

## Product decisions

- Python with PySide6 / Qt 6 Widgets.
- Two equal Commander-style panes sharing document sessions.
- HDF5 graph semantics: link path and object identity are different concepts.
- Lazy, paged metadata and dataset reads.
- Safe-copy editing is the default; the original is replaced only after validation.
- Russian and English UI; Russian is the default.
- Domain, application, HDF5 infrastructure, and Qt presentation are separate layers.

## Milestones

### M1 — foundation and read-only vertical slice (completed)

- [x] Project metadata and source layout.
- [x] Language requirement recorded.
- [x] HDF5 domain types and repository protocol.
- [x] h5py backend with graph-safe, indexed link paging.
- [x] Generated fixture files and backend tests.
- [x] Launchable two-pane window.
- [x] Object inspector with properties, attributes, and paged dataset table.

### M2 — safe basic editing (completed)

- [x] Working-copy session and recovery manifest.
- [x] Save, Save As, and Discard.
- [x] Scalar attribute and dataset-cell commands.
- [x] Create group and rename link commands.
- [x] Undo/redo stack.
- [x] External modification detection and backup.

### M3 — richer HDF5 operations

- [x] Dataset creation dialog and safe expansion within maxshape.
- [ ] Destructive dataset shrinking with disk-backed undo snapshots.
- [x] Undoable object/link copying inside and across documents.
- [x] Link creation, safe deletion, and coordinated move inside/across documents.
- [x] Object/reference inspectors and VDS/dimension-scale details.
- [x] Metadata search and chunked comparison.
- [x] Export CSV/NPY and optional visualization.

### M4 — extensibility, resilience, and distribution

- [ ] Versioned entry-point plugin API and sample plugin.
- [x] Process-isolated validation before commit.
- [ ] Crash injection and large-file performance tests.
- [ ] Packaging and CI matrix for Windows, macOS, and Linux.
- [ ] User and developer documentation with a verified support matrix.

## Current risks

- Some HDF5 datatypes are only partially representable by NumPy/h5py. Unsupported editing must
  remain explicitly read-only.
- External storage, external links, and VDS can affect multiple physical files and cannot share
  the same atomic-save guarantee as a single local file.
- h5py serializes HDF5 calls; long operations must not run on the GUI thread and real parallel
  HDF5 work requires processes.
- A complete safe save may require disk space close to the original file size when filesystem
  cloning is unavailable.

## Definition of done for the first usable release

- [x] Open generated HDF5 files without loading dataset payloads eagerly.
- [x] Browse hard, soft, external, and broken links without infinite recursion.
- [x] Inspect properties, attributes, and small paged dataset slices.
- [x] Use the same or different files in the two panes.
- [x] Switch Russian/English UI, with Russian selected on first launch.
- [x] Edit supported scalar values in a working copy, then Save or Discard.
- [x] Reopen a saved file and verify the edits.
- [x] Pass unit, integration, GUI smoke, lint, and type checks.

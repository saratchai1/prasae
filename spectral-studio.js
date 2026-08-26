// PDD22 production note:
// The legacy Spectral Studio uses generic data/plots/{numeric-id} band assets,
// which are not the authoritative PDD22 participating-only dataset.
// It is intentionally disabled on this branch to prevent cross-dataset mixing.
// Re-enable only after PDD22-specific spectral band assets are built and audited.
(() => {
  window.PDD22_SPECTRAL_STUDIO_DISABLED = true;
})();

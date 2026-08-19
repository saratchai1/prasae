// Prasae Spectral Studio R2 adapter.
// Routes only spectral manifests/band PNGs to the configured R2-backed Worker.
// Everything else uses the browser's native fetch/image behavior unchanged.
// Remote failure falls back to the existing same-origin GitHub Pages assets.

(() => {
  const VERSION = '20260819-2117';
  const CONFIG_URL = `data/spectral_asset_config.json?v=${VERSION}`;
  const nativeFetch = window.fetch.bind(window);
  const remotePlots = new Set();

  let configPromise = null;

  function cleanBase(value) {
    return String(value || '').replace(/\/+$/, '');
  }

  function isAbsoluteHttp(value) {
    return /^https?:\/\//i.test(String(value || ''));
  }

  function parseLocalManifestUrl(value) {
    const text = typeof value === 'string'
      ? value
      : value instanceof Request
        ? value.url
        : String(value || '');
    const url = new URL(text, window.location.href);
    const match = url.pathname.match(/\/data\/plots\/(\d+)\/spectral_manifest\.json$/);
    return match ? { plotId: match[1], url } : null;
  }

  function parseLocalBandUrl(value) {
    const text = String(value || '');
    const url = new URL(text, window.location.href);
    const match = url.pathname.match(
      /\/data\/plots\/(\d+)\/(band_(?:B02|B03|B04|B08|B11|B12)_\d{4}-\d{2}\.png)$/
    );
    return match ? { plotId: match[1], filename: match[2] } : null;
  }

  async function loadConfig() {
    if (configPromise) return configPromise;
    configPromise = (async () => {
      try {
        const response = await nativeFetch(CONFIG_URL, { cache: 'no-store' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const config = await response.json();
        const rules = config?.rules || {};
        if (
          rules.exact_declared_month_only !== true ||
          rules.nearest_month_fallback !== false ||
          rules.interpolation !== false ||
          rules.synthetic_imagery !== false
        ) {
          throw new Error('Spectral asset config violates temporal-integrity rules');
        }
        return config;
      } catch (error) {
        console.warn('Spectral R2 config unavailable; using local assets only:', error);
        return null;
      }
    })();
    return configPromise;
  }

  window.fetch = async function routedFetch(input, init) {
    const parsed = parseLocalManifestUrl(input);
    if (!parsed) return nativeFetch(input, init);

    const config = await loadConfig();
    const primaryBase = cleanBase(config?.primary?.base_url);
    if (!primaryBase) return nativeFetch(input, init);

    const remoteUrl = `${primaryBase}/plots/${encodeURIComponent(parsed.plotId)}/spectral_manifest.json?v=${VERSION}`;
    try {
      const response = await nativeFetch(remoteUrl, {
        ...(init || {}),
        cache: 'no-store',
        mode: 'cors'
      });
      if (response.ok) {
        remotePlots.add(parsed.plotId);
        return response;
      }
      console.info(`Spectral R2 manifest ${parsed.plotId}: HTTP ${response.status}; using local fallback`);
    } catch (error) {
      console.info(`Spectral R2 manifest ${parsed.plotId} unavailable; using local fallback`, error);
    }
    remotePlots.delete(parsed.plotId);
    return nativeFetch(input, init);
  };

  const srcDescriptor = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
  if (srcDescriptor?.get && srcDescriptor?.set) {
    Object.defineProperty(HTMLImageElement.prototype, 'src', {
      configurable: srcDescriptor.configurable,
      enumerable: srcDescriptor.enumerable,
      get: srcDescriptor.get,
      set(value) {
        const parsed = parseLocalBandUrl(value);
        if (!parsed || !remotePlots.has(parsed.plotId)) {
          srcDescriptor.set.call(this, value);
          return;
        }

        const route = async () => {
          const config = await loadConfig();
          const primaryBase = cleanBase(config?.primary?.base_url);
          if (!primaryBase) {
            srcDescriptor.set.call(this, value);
            return;
          }
          const remoteUrl = `${primaryBase}/plots/${encodeURIComponent(parsed.plotId)}/${encodeURIComponent(parsed.filename)}?v=${VERSION}`;
          if (isAbsoluteHttp(remoteUrl) && new URL(remoteUrl).origin !== window.location.origin) {
            this.crossOrigin = 'anonymous';
          }
          srcDescriptor.set.call(this, remoteUrl);
        };

        // The manifest fetch occurs before band loads in Spectral Studio, so config is
        // normally already resolved. Keep this async path to preserve local fallback.
        void route();
      }
    });
  } else {
    console.warn('Spectral R2 adapter could not install image routing; local assets remain available.');
  }
})();

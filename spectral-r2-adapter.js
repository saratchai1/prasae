// Prasae Spectral Studio R2 adapter.
// Prefer same-origin deployed spectral assets first, then fall back to the configured
// R2-backed Worker only when the local manifest is unavailable. This prevents a stale
// or partial remote manifest from hiding assets that are already deployed on Pages.
// Everything else uses the browser's native fetch/image behavior unchanged.

(() => {
  const VERSION = '20260820-0445';
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

    // Local-first is intentional. Assets explicitly deployed with the site are the
    // authoritative browser visualization package for that plot.
    let localResponse = null;
    try {
      localResponse = await nativeFetch(input, { ...(init || {}), cache: 'no-store' });
      if (localResponse.ok) {
        remotePlots.delete(parsed.plotId);
        return localResponse;
      }
    } catch (error) {
      console.info(`Local spectral manifest ${parsed.plotId} unavailable; trying R2 fallback`, error);
    }

    const config = await loadConfig();
    const primaryBase = cleanBase(config?.primary?.base_url);
    if (primaryBase) {
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
        console.info(`Spectral R2 manifest ${parsed.plotId}: HTTP ${response.status}; no remote spectral package`);
      } catch (error) {
        console.info(`Spectral R2 manifest ${parsed.plotId} unavailable`, error);
      }
    }

    remotePlots.delete(parsed.plotId);
    if (localResponse) return localResponse;
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

        void route();
      }
    });
  } else {
    console.warn('Spectral R2 adapter could not install image routing; local assets remain available.');
  }
})();

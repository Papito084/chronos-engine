/**
 * Utility functions for robust numerical scaling and formatting across ChronosEngine frontend.
 * Protects against raw fixed-point 10^8 integers leaking from low-level engine events.
 */

export function normalizePrice(p: number | string | null | undefined): number {
  if (p == null) return 0;
  const num = typeof p === 'string' ? parseFloat(p) : Number(p);
  if (isNaN(num)) return 0;
  // If price is >= 1e7 (e.g. 6,500,000,000,000 in scale 10^8), scale down
  if (Math.abs(num) >= 1e7) {
    return num / 1e8;
  }
  return num;
}

export function normalizeQty(q: number | string | null | undefined): number {
  if (q == null) return 0;
  const num = typeof q === 'string' ? parseFloat(q) : Number(q);
  if (isNaN(num)) return 0;
  // If quantity is >= 1e6 (e.g. 50,000,000 for 0.5 BTC in scale 10^8), scale down
  if (Math.abs(num) >= 1e6) {
    return num / 1e8;
  }
  return num;
}

export function formatPrice(p: number | string | null | undefined, decimals: number = 2): string {
  const val = normalizePrice(p);
  return val.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatQty(q: number | string | null | undefined, decimals: number = 4): string {
  const val = normalizeQty(q);
  return val.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/**
 * price-landscape/usePriceCounter.js — animate between two PROVEN prices.
 *
 * Only ever tweens from one real price to another real price. When the target is null (no proven
 * price) it returns null at once: an unverified price is never "counted up" into a fake value.
 * With prefers-reduced-motion the new value is shown immediately.
 */

import { useEffect, useRef, useState } from 'react';

export const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;

/** @param {number | null} target @param {number} [duration] ms */
export function usePriceCounter(target, duration = 420) {
  const [shown, setShown] = useState(target);
  const from = useRef(target);

  useEffect(() => {
    if (!Number.isFinite(target) || !Number.isFinite(from.current) || prefersReducedMotion()) {
      from.current = target;
      setShown(target);
      return undefined;
    }
    const start = from.current;
    const t0 = performance.now();
    let frame = requestAnimationFrame(function tick(now) {
      const p = Math.min((now - t0) / duration, 1);
      const eased = 1 - (1 - p) ** 3;
      setShown(p < 1 ? Math.round(start + (target - start) * eased) : target);
      if (p < 1) frame = requestAnimationFrame(tick);
    });
    from.current = target;
    return () => cancelAnimationFrame(frame);
  }, [target, duration]);

  return Number.isFinite(target) ? shown : null;
}

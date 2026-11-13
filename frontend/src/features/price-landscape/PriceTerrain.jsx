/**
 * price-landscape/PriceTerrain.jsx — the 3D stage for the calendar.
 *
 * Pure CSS: a perspective container and a gently tilted board; each tile is lifted with
 * transform: translateY (see PriceLandscape.css). The tilt shrinks on tablets, disappears on
 * phones and under prefers-reduced-motion, so the calendar always stays a readable grid.
 * `settling` re-triggers the rise animation when a new month's prices arrive.
 */

/** @param {{ children: React.ReactNode, settling: boolean, monthKey: string }} props */
export default function PriceTerrain({ children, settling, monthKey }) {
  return (
    <div className="pl-terrain">
      <div className={`pl-terrain__board${settling ? ' is-settling' : ''}`} key={monthKey}>
        {children}
      </div>
    </div>
  );
}

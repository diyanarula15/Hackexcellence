/**
 * hud/Slot.jsx — a named, grid-aligned injection point.
 *
 * Slots are empty wrappers reserved for hackathon widgets. An empty slot is
 * invisible and click-through; pass children to fill it. Each slot carries a
 * `data-slot` attribute so it is easy to grep for and to see in DevTools
 * (press "G" in the browser to outline every slot).
 */

/**
 * @param {{ name: string, className?: string, children?: React.ReactNode }} props
 *   name — slot identifier, e.g. `HACKATHON_PREFERENCES_BUDGET_SLOT`.
 *   className — positioning class from hud.css (e.g. `slot--preferences`).
 * @returns {JSX.Element}
 */
export default function Slot({ name, className = '', children }) {
  return (
    <div className={`slot ${className}`} data-slot={name}>
      {children}
    </div>
  );
}

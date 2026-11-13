/**
 * price-landscape/PriceLegend.jsx - what height, shade and the special tiles mean.
 * The low/high labels are the proven prices of the month on screen (nothing estimated).
 */

import { formatINR } from './landscapeModel.js';

/** @param {{ range: { min: number, max: number } | null }} props */
export default function PriceLegend({ range }) {
  return (
    <div className="pl-legend" aria-label="Legend">
      <div className="pl-legend__ramp">
        <span className="pl-legend__end">{range ? formatINR(range.min) : 'Lower'}</span>
        <span className="pl-legend__bar" aria-hidden="true" />
        <span className="pl-legend__end">{range ? formatINR(range.max) : 'Higher'}</span>
      </div>
      <p className="pl-legend__caption">Lower and lighter tiles cost less. Height shows price only.</p>
      <ul className="pl-legend__keys">
        <li><span className="pl-key pl-key--infeasible" aria-hidden="true" />No trip possible</li>
        <li><span className="pl-key pl-key--incomplete" aria-hidden="true" />Price not verified</li>
        <li><span className="pl-key pl-key--outside" aria-hidden="true" />Not available</li>
        <li><span className="pl-key pl-key--reference" aria-hidden="true" />Your date</li>
      </ul>
    </div>
  );
}

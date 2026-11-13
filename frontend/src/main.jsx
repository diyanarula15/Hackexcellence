/**
 * main.jsx - entry point. Loads design tokens FIRST (the 3D scene reads the
 * colour variables from the document), then mounts <App />.
 */

import './theme/tokens.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

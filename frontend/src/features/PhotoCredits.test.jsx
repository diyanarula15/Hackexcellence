import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { getPhotoCredits } = vi.hoisted(() => ({ getPhotoCredits: vi.fn() }));
vi.mock('../services/hotelsApi.js', () => ({ getPhotoCredits }));

import PhotoCredits from './PhotoCredits.jsx';

beforeEach(() => {
  getPhotoCredits.mockResolvedValue({
    credits: [
      { file: 'first.jpg', used_for: 'Hotel A', author: 'Artist A', license: 'CC BY', license_url: 'https://example.test/license-a', source: 'Wikimedia', source_url: 'https://example.test/source-a' },
      { file: 'last.jpg', used_for: 'Hotel B', author: 'Artist B', license: 'CC0', license_url: 'https://example.test/license-b', source: 'Wikimedia', source_url: 'https://example.test/source-b' },
    ],
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('PhotoCredits dialog keyboard focus', () => {
  it('wraps Tab at both ends, closes on Escape, and restores focus to its opener', async () => {
    const user = userEvent.setup();
    render(<PhotoCredits />);

    const opener = screen.getByRole('button', { name: 'Photo credits' });
    await user.click(opener);
    const dialog = await screen.findByRole('dialog', { name: 'Photo credits' });
    await waitFor(() => expect(dialog.querySelectorAll('a[href]')).toHaveLength(4));
    expect(getPhotoCredits).toHaveBeenCalledOnce();

    const controls = dialog.querySelectorAll('button:not(:disabled), a[href]');
    const first = controls[0];
    const last = controls[controls.length - 1];

    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(last);

    last.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(document.activeElement).toBe(first);

    first.focus();
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(last);

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });
});

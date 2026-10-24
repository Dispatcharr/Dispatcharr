import { createRef, useState } from 'react';
import { MantineProvider } from '@mantine/core';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ScreenshotText,
  SensitiveValue,
  SensitiveTextInput,
  SensitivePasswordInput,
} from '../SensitiveFields.jsx';
import useScreenshotMode from '../../store/useScreenshotMode.js';
import { HIDDEN_VALUE } from '../../utils/screenshotMode.js';

const url = 'https://example.invalid/live?password=example-secret';
const show = (children) =>
  render(<MantineProvider>{children}</MantineProvider>);
const toggle = () => act(() => useScreenshotMode.getState().toggle());

describe('screenshot-safe presentation', () => {
  beforeEach(() => {
    sessionStorage.clear();
    useScreenshotMode.setState({ enabled: false });
  });

  it('masks URL text and its tooltip, and restores both when switched off', async () => {
    show(<SensitiveValue withTooltip>{url}</SensitiveValue>);
    expect(screen.getByText(url)).toBeInTheDocument();
    toggle();
    const value = screen.getByText(HIDDEN_VALUE);
    expect(screen.queryByText(url)).not.toBeInTheDocument();
    fireEvent.mouseEnter(value);
    expect(await screen.findByRole('tooltip')).toHaveTextContent(HIDDEN_VALUE);
    expect(screen.getByRole('tooltip')).not.toHaveTextContent(url);
    fireEvent.mouseLeave(value);
    toggle();
    expect(screen.getAllByText(url).length).toBeGreaterThan(0);
  });

  it('leaves public IPs and explicitly non-sensitive text unchanged', () => {
    useScreenshotMode.setState({ enabled: true });
    show(
      <>
        <SensitiveTextInput label="Public IP" defaultValue="203.0.113.7" />
        <SensitiveValue sensitive={false}>ExampleUser</SensitiveValue>
      </>
    );
    expect(screen.getByLabelText('Public IP').type).toBe('text');
    expect(screen.getByText('ExampleUser')).toBeInTheDocument();
  });

  it.each([
    { label: 'Server URL', name: 'server_url' },
    { label: 'Sample', sensitive: true },
    { label: 'Target', value: url, onChange: () => {} },
    { label: 'XC Password', value: 'example-secret', onChange: () => {} },
    { label: 'Credentials', type: 'password' },
    { label: 'Username', value: 'ExampleUser', onChange: () => {} },
    { label: 'New Username', value: 'ExampleUser', onChange: () => {} },
  ])(
    'masks the input without changing its submitted value: $label',
    (props) => {
      const ref = createRef();
      const submitted = vi.fn();
      const { label, ...inputProps } = props;
      show(
        <form
          onSubmit={(event) => {
            event.preventDefault();
            submitted(
              new FormData(event.currentTarget).get(inputProps.name || 'field')
            );
          }}
        >
          <SensitiveTextInput
            name="field"
            label={label}
            defaultValue={inputProps.value === undefined ? url : undefined}
            {...inputProps}
            ref={ref}
          />
          <button type="submit">Save</button>
        </form>
      );
      const input = screen.getByLabelText(label);
      const original = input.value;
      expect(ref.current).toBe(input);
      toggle();
      expect(input).toHaveAttribute('type', 'password');
      expect(input).not.toHaveAttribute('readonly');
      expect(input).toHaveValue(original);
      fireEvent.click(screen.getByText('Save'));
      expect(submitted).toHaveBeenCalledWith(original);
      toggle();
      expect(input).not.toHaveAttribute('readonly');
      expect(input.type).toBe(props.type || 'text');
    }
  );

  it('overrides an already revealed password and disables its reveal control', () => {
    const { container } = show(
      <SensitivePasswordInput
        label="Password"
        defaultValue="example-secret"
        visible
      />
    );
    const input = screen.getByLabelText('Password');
    expect(input).toHaveAttribute('type', 'text');
    toggle();
    expect(input).toHaveAttribute('type', 'password');
    expect(input).toHaveValue('example-secret');
    expect(input).not.toHaveAttribute('readonly');
    expect(container.querySelector('button')).toBeDisabled();
    toggle();
    expect(input).toHaveAttribute('type', 'text');
    expect(container.querySelector('button')).not.toBeDisabled();
  });

  it('names password visibility controls and preserves visibility callbacks', () => {
    const onVisibilityChange = vi.fn();
    show(
      <SensitivePasswordInput
        label="Password"
        defaultValue="example-secret"
        onVisibilityChange={onVisibilityChange}
      />
    );
    fireEvent.keyDown(screen.getByRole('button', { name: 'Show password' }), {
      key: ' ',
    });
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'text');
    expect(onVisibilityChange).toHaveBeenLastCalledWith(true);
    fireEvent.keyDown(screen.getByRole('button', { name: 'Hide password' }), {
      key: ' ',
    });
    expect(screen.getByLabelText('Password')).toHaveAttribute(
      'type',
      'password'
    );
    expect(onVisibilityChange).toHaveBeenLastCalledWith(false);
  });

  it('does not enable the visibility toggle of a disabled password field', () => {
    show(
      <SensitivePasswordInput
        label="Password"
        defaultValue="example-secret"
        disabled
      />
    );
    expect(
      screen.getByRole('button', { name: 'Show password' })
    ).toBeDisabled();
  });

  it('lets users edit and submit masked URL, username and password fields', () => {
    const submit = vi.fn();
    const EditForm = () => {
      const [values, setValues] = useState({
        url,
        username: 'ExampleUser',
        password: 'example-secret',
      });
      const update = (field) => (event) =>
        setValues((current) => ({ ...current, [field]: event.target.value }));
      return (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            submit(values);
          }}
        >
          <SensitiveTextInput
            label="URL"
            value={values.url}
            onChange={update('url')}
          />
          <SensitiveTextInput
            label="Username"
            value={values.username}
            onChange={update('username')}
          />
          <SensitivePasswordInput
            label="Password"
            value={values.password}
            onChange={update('password')}
          />
          <button type="submit">Save</button>
        </form>
      );
    };
    useScreenshotMode.setState({ enabled: true });
    show(<EditForm />);
    for (const [label, value] of [
      ['URL', 'https://changed.invalid'],
      ['Username', 'ChangedUser'],
      ['Password', 'changed-secret'],
    ]) {
      const input = screen.getByLabelText(label);
      expect(input).toHaveAttribute('type', 'password');
      expect(input).not.toHaveAttribute('readonly');
      fireEvent.change(input, { target: { value } });
      expect(input).toHaveValue(value);
    }
    fireEvent.click(screen.getByText('Save'));
    expect(submit).toHaveBeenCalledWith({
      url: 'https://changed.invalid',
      username: 'ChangedUser',
      password: 'changed-secret',
    });
  });

  it('preserves read-only fields explicitly configured by their caller', () => {
    useScreenshotMode.setState({ enabled: true });
    show(
      <>
        <SensitiveTextInput label="Generated URL" defaultValue={url} readOnly />
        <SensitivePasswordInput
          label="Managed password"
          defaultValue="example-secret"
          readOnly
        />
      </>
    );
    expect(screen.getByLabelText('Generated URL')).toHaveAttribute('readonly');
    expect(screen.getByLabelText('Managed password')).toHaveAttribute(
      'readonly'
    );
  });

  it('redacts URL literals inside nested messages without changing other text', () => {
    show(
      <ScreenshotText>
        Failed: <strong>{url}</strong> for ExampleUser (203.0.113.7)
      </ScreenshotText>
    );
    expect(screen.getByText(url)).toBeInTheDocument();
    toggle();
    expect(screen.queryByText(url)).not.toBeInTheDocument();
    expect(screen.getByText(HIDDEN_VALUE).tagName).toBe('STRONG');
    expect(
      screen.getByText(/for ExampleUser \(203.0.113.7\)/)
    ).toBeInTheDocument();
  });
});

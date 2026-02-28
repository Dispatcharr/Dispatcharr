import { Field, FieldDescription, FieldLabel } from '~/components/ui/field';
import { Input } from '~/components/ui/input';

export default function InputField({
  id,
  label,
  description,
  placeholder,
  value,
  onChange,
  onKeyDown,
}: {
  id?: string;
  label: string;
  description?: string;
  placeholder?: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void;
}) {
  const inputId =
    id || `input-field-${label.toLowerCase().replace(/\s+/g, '-')}`;
  return (
    <Field className="gap-1">
      <FieldLabel htmlFor={inputId}>{label}</FieldLabel>
      {description && (
        <FieldDescription className="text-xs">{description}</FieldDescription>
      )}
      <Input
        id={inputId}
        type="text"
        placeholder={placeholder || undefined}
        value={value}
        onChange={onChange}
        onKeyDown={onKeyDown}
      />
    </Field>
  );
}

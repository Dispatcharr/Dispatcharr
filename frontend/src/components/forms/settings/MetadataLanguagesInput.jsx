import { useState } from 'react';
import {
  ActionIcon,
  Combobox,
  Group,
  Pill,
  PillsInput,
  ScrollArea,
  useCombobox,
} from '@mantine/core';
import { GripVertical } from 'lucide-react';
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  arrayMove,
  rectSortingStrategy,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import {
  MAX_METADATA_LANGUAGES,
  METADATA_LANGUAGE_OPTIONS,
  metadataLanguageLabel,
} from '../../../utils/vodMetadataLanguages.js';

function LanguagePill({ language, disabled, onRemove }) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: language, disabled });
  return (
    <Pill
      ref={setNodeRef}
      disabled={disabled}
      withRemoveButton
      onRemove={onRemove}
      removeButtonProps={{
        'aria-label': `Remove ${metadataLanguageLabel(language)}`,
        'aria-hidden': false,
        tabIndex: 0,
        disabled,
      }}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.6 : 1,
      }}
    >
      <Group component="span" gap={4} wrap="nowrap">
        <ActionIcon
          {...attributes}
          {...listeners}
          type="button"
          aria-label={`Reorder ${metadataLanguageLabel(language)}`}
          title="Drag or use Space and arrow keys to change display order"
          size={18}
          variant="transparent"
          color="gray"
          disabled={disabled}
          style={{ cursor: disabled ? undefined : 'grab', touchAction: 'none' }}
          onClick={(event) => event.stopPropagation()}
        >
          <GripVertical size={13} />
        </ActionIcon>
        {metadataLanguageLabel(language)}
      </Group>
    </Pill>
  );
}

export default function MetadataLanguagesInput({
  value,
  onChange,
  disabled,
  error,
}) {
  const [search, setSearch] = useState('');
  const combobox = useCombobox({
    onDropdownClose: () => combobox.resetSelectedOption(),
  });
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );
  const options = [
    ...METADATA_LANGUAGE_OPTIONS,
    ...value
      .filter(
        (language) =>
          !METADATA_LANGUAGE_OPTIONS.some((option) => option.value === language)
      )
      .map((language) => ({ value: language, label: language })),
  ].filter((option) =>
    option.label.toLowerCase().includes(search.toLowerCase())
  );
  const remove = (language) =>
    !disabled && onChange(value.filter((entry) => entry !== language));
  return (
    <Combobox
      store={combobox}
      withinPortal
      onOptionSubmit={(language) => {
        if (disabled) return;
        if (value.includes(language)) remove(language);
        else if (value.length < MAX_METADATA_LANGUAGES)
          onChange([...value, language]);
        setSearch('');
      }}
    >
      <Combobox.DropdownTarget>
        <PillsInput
          label="Metadata languages"
          description="Up to 5 translations. The first available language is shown in the Library."
          disabled={disabled}
          error={error}
          onClick={() => !disabled && combobox.openDropdown()}
        >
          <Pill.Group>
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragStart={() => combobox.closeDropdown()}
              onDragEnd={({ active, over }) => {
                if (disabled || !over || active.id === over.id) return;
                const from = value.indexOf(active.id),
                  to = value.indexOf(over.id);
                if (from >= 0 && to >= 0) onChange(arrayMove(value, from, to));
              }}
            >
              <SortableContext items={value} strategy={rectSortingStrategy}>
                {value.map((language) => (
                  <LanguagePill
                    key={language}
                    language={language}
                    disabled={disabled}
                    onRemove={() => remove(language)}
                  />
                ))}
              </SortableContext>
            </DndContext>
            <Combobox.EventsTarget>
              <PillsInput.Field
                aria-label="Metadata languages"
                value={search}
                disabled={disabled}
                onFocus={() => !disabled && combobox.openDropdown()}
                onBlur={() => combobox.closeDropdown()}
                onChange={(event) => {
                  setSearch(event.currentTarget.value);
                  combobox.openDropdown();
                  combobox.updateSelectedOptionIndex();
                }}
                onKeyDown={(event) => {
                  if (
                    event.key === 'Backspace' &&
                    !search &&
                    value.length &&
                    !disabled
                  ) {
                    event.preventDefault();
                    remove(value.at(-1));
                  }
                }}
              />
            </Combobox.EventsTarget>
          </Pill.Group>
        </PillsInput>
      </Combobox.DropdownTarget>
      <Combobox.Dropdown>
        <Combobox.Options>
          <ScrollArea.Autosize mah={220} type="scroll">
            {options.map((option) => (
              <Combobox.Option
                key={option.value}
                value={option.value}
                active={value.includes(option.value)}
                disabled={
                  disabled ||
                  (!value.includes(option.value) &&
                    value.length >= MAX_METADATA_LANGUAGES)
                }
              >
                {option.label}
              </Combobox.Option>
            ))}
            {!options.length && (
              <Combobox.Empty>No matching language</Combobox.Empty>
            )}
          </ScrollArea.Autosize>
        </Combobox.Options>
      </Combobox.Dropdown>
    </Combobox>
  );
}

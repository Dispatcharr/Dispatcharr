import React, { useMemo, useState } from 'react';
import {
  Accordion,
  AccordionControl,
  AccordionItem,
  AccordionPanel,
  Stack,
} from '@mantine/core';
import { Field } from './Field.jsx';

const PluginFieldList = ({ plugin, settings, updateField }) => {
  const fields = useMemo(() => plugin.fields || [], [plugin.fields]);

  const sectionMarkers = useMemo(
    () => fields.filter((f) => f.type === 'section'),
    [fields]
  );
  const sectionIds = useMemo(
    () => new Set(sectionMarkers.map((s) => s.id)),
    [sectionMarkers]
  );

  const [openSections, setOpenSections] = useState(() =>
    sectionMarkers.filter((s) => !s.collapsed).map((s) => s.id)
  );

  const ungroupedFields = fields.filter(
    (f) => f.type !== 'section' && (!f.section || !sectionIds.has(f.section))
  );

  const renderField = (f) => (
    <Field
      key={f.id}
      field={f}
      value={settings?.[f.id]}
      onChange={updateField}
      pluginKey={plugin.key}
    />
  );

  return (
    <Stack gap="md">
      {ungroupedFields.map(renderField)}

      {sectionMarkers.length > 0 && (
        <Accordion
          multiple
          variant="separated"
          value={openSections}
          onChange={setOpenSections}
        >
          {sectionMarkers.map((section) => {
            const members = fields.filter((f) => f.section === section.id);
            return (
              <AccordionItem key={section.id} value={section.id}>
                <AccordionControl>{section.label || section.id}</AccordionControl>
                <AccordionPanel>
                  <Stack gap="md">{members.map(renderField)}</Stack>
                </AccordionPanel>
              </AccordionItem>
            );
          })}
        </Accordion>
      )}
    </Stack>
  );
};

export default PluginFieldList;

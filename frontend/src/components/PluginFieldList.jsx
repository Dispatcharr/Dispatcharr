import React from 'react';
import { Field } from './Field.jsx';

const PluginFieldList = ({ plugin, settings, updateField }) => {
  return plugin.fields.map((f) => (
    <Field
      key={f.id}
      field={f}
      value={settings?.[f.id]}
      onChange={updateField}
    />
  ));
};

export default PluginFieldList;

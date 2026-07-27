export const getSystemSettingsFormInitialValues = () => {
  return {
    max_system_events: 100,
    log_max_mb: 10,
    log_keep: 5,
    preferred_region: '',
    auto_import_mapped_files: true,
    enable_ip_lookup: true,
    catchup_enabled: true,
  };
};

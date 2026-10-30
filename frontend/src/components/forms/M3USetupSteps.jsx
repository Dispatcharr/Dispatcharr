import { Stepper } from '@mantine/core';

const M3USetupSteps = ({
  stage,
  accountType = 'XC',
  onSelect,
  contentAvailable = false,
}) => {
  const steps = [
    ['account', 'Account'],
    ['content', 'Settings'],
    ...(accountType === 'XC' ? [['epg', 'EPG']] : []),
    ['categories', 'Content'],
  ];
  return (
    <Stepper
      active={Math.max(
        0,
        steps.findIndex(([key]) => key === stage)
      )}
      size="xs"
      mb="md"
      aria-label="M3U setup progress"
      onStepClick={onSelect ? (index) => onSelect(steps[index][0]) : undefined}
    >
      {steps.map(([key, label]) => (
        <Stepper.Step
          key={key}
          label={label}
          aria-current={stage === key ? 'step' : undefined}
          aria-disabled={
            !onSelect ||
            (key !== 'account' && !(key === 'content' && contentAvailable))
          }
          allowStepSelect={
            !!onSelect &&
            (key === 'account' || (key === 'content' && contentAvailable))
          }
        />
      ))}
    </Stepper>
  );
};

export default M3USetupSteps;

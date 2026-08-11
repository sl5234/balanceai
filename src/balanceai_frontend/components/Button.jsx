import { Pressable, Text, View } from 'react-native';
import { useTheme } from '../theme';

export function Button({ children, variant = 'primary', onPress, disabled, block, style = {}, textStyle = {}, icon }) {
  const t = useTheme();

  const base = {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    borderRadius: t.radius.md,
    paddingVertical: t.space[2],
    paddingHorizontal: t.space[3] * 1.2,
    borderWidth: 1,
    borderColor: 'transparent',
    backgroundColor: 'transparent',
  };

  const variantStyle = (pressed) => {
    if (variant === 'primary') {
      return { backgroundColor: pressed ? t.accentRamp[700] : t.accent };
    }
    if (variant === 'secondary') {
      return { borderColor: t.divider, backgroundColor: pressed ? 'rgba(32,30,29,0.07)' : t.surface };
    }
    if (variant === 'ghost') {
      return { paddingHorizontal: t.space[1], backgroundColor: pressed ? 'rgba(0,136,176,0.1)' : 'transparent' };
    }
    return {};
  };

  const textColor = variant === 'primary' ? t.bg : variant === 'ghost' ? t.accent : t.text;

  return (
    <Pressable
      onPress={disabled ? undefined : onPress}
      disabled={disabled}
      style={({ pressed }) => [base, variantStyle(pressed), block && { width: '100%' }, disabled && { opacity: 0.45 }, style]}
    >
      {icon}
      <Text style={[{ fontFamily: t.fontHeading, fontWeight: '600', fontSize: 14, lineHeight: 17, color: textColor }, textStyle]}>
        {children}
      </Text>
    </Pressable>
  );
}

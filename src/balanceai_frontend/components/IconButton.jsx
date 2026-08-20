import { Pressable } from 'react-native';
import { useTheme } from '../theme';

export function IconButton({ children, onPress, size = 36, circle = false, bordered = true, borderColor, backgroundColor, style = {} }) {
  const t = useTheme();
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        {
          width: size,
          height: size,
          borderRadius: circle ? size / 2 : t.radius.md,
          alignItems: 'center',
          justifyContent: 'center',
          borderWidth: bordered ? 1 : 0,
          borderColor: borderColor ?? t.divider,
          backgroundColor: backgroundColor ?? (pressed ? 'rgba(32,30,29,0.07)' : 'transparent'),
        },
        style,
      ]}
    >
      {children}
    </Pressable>
  );
}

import { View, Pressable } from 'react-native';
import { useTheme } from '../theme';

export function Card({ children, style = {}, onPress, elevation }) {
  const t = useTheme();
  const Container = onPress ? Pressable : View;
  const shadow = elevation === 'sm' ? t.shadowSm : elevation === 'md' ? t.shadowMd : elevation === 'lg' ? t.shadowLg : null;

  return (
    <Container
      onPress={onPress}
      style={[
        {
          backgroundColor: t.surface,
          borderRadius: t.radius.md,
          padding: t.space[3],
          gap: t.space[2],
        },
        shadow,
        style,
      ]}
    >
      {children}
    </Container>
  );
}

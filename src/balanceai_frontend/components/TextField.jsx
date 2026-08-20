import { useState } from 'react';
import { TextInput } from 'react-native';
import { useTheme } from '../theme';

export function TextField({ value, onChangeText, placeholder, secureTextEntry, keyboardType, autoCapitalize = 'sentences', onFocus, onBlur, style = {}, minHeight = 36 }) {
  const t = useTheme();
  const [focused, setFocused] = useState(false);

  return (
    <TextInput
      value={value}
      onChangeText={onChangeText}
      placeholder={placeholder}
      placeholderTextColor="rgba(32,30,29,0.65)"
      secureTextEntry={secureTextEntry}
      keyboardType={keyboardType}
      autoCapitalize={autoCapitalize}
      cursorColor={t.accent}
      selectionColor={t.accent}
      onFocus={(e) => { setFocused(true); onFocus?.(e); }}
      onBlur={(e) => { setFocused(false); onBlur?.(e); }}
      style={[
        {
          width: '100%',
          minHeight,
          paddingVertical: 6,
          paddingHorizontal: 10,
          fontFamily: t.fontBody,
          fontSize: 14,
          color: t.text,
          backgroundColor: t.surface,
          borderWidth: 1,
          borderColor: focused ? t.accent : t.divider,
          borderRadius: t.radius.md,
        },
        style,
      ]}
    />
  );
}

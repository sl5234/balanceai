import { useEffect, useRef } from 'react';
import { View, Text, TextInput, Pressable, Animated } from 'react-native';
import { useTheme } from '../../theme';
import { Icon } from '../Icon';
import { ReceiptPlaceholder } from './PhotoMessage';

export function Composer({
  text, onChangeText, onSend, onFocus, onBlur,
  attachOpen, onToggleAttach, onOpenCamera,
  staged, onUnstage,
}) {
  const t = useTheme();
  const rotation = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(rotation, { toValue: attachOpen ? 1 : 0, duration: 180, useNativeDriver: true }).start();
  }, [attachOpen]);

  const rotate = rotation.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '45deg'] });

  return (
    <View style={{ paddingHorizontal: 14, paddingBottom: 6 }}>
      {attachOpen && (
        <View style={{ flexDirection: 'row', gap: 8, paddingHorizontal: 4, paddingBottom: 9 }}>
          <Pressable
            onPress={onOpenCamera}
            style={({ pressed }) => ({
              flexDirection: 'row', alignItems: 'center', gap: 8,
              borderWidth: 1, borderColor: t.divider, borderRadius: t.radius.md,
              paddingVertical: 10, paddingHorizontal: 18,
              backgroundColor: pressed ? 'rgba(32,30,29,0.07)' : t.surface,
            })}
          >
            <Icon name="camera" size={18} color={t.accent} />
            <Text style={{ fontFamily: t.fontHeading, fontWeight: '600', fontSize: 14, color: t.text }}>Camera</Text>
          </Pressable>
        </View>
      )}

      {staged && (
        <View style={{ paddingHorizontal: 4, paddingBottom: 9 }}>
          <View style={{ width: 56 }}>
            <ReceiptPlaceholder width={56} height={72} />
            <Pressable
              onPress={onUnstage}
              style={{
                position: 'absolute', top: -7, right: -7, width: 20, height: 20, borderRadius: 10,
                backgroundColor: t.text, alignItems: 'center', justifyContent: 'center',
              }}
            >
              <Text style={{ color: t.bg, fontSize: 12, lineHeight: 14 }}>×</Text>
            </Pressable>
          </View>
        </View>
      )}

      <View style={{ flexDirection: 'row', alignItems: 'flex-end', gap: 8 }}>
        <Pressable
          onPress={onToggleAttach}
          style={{
            width: 36, height: 36, borderRadius: t.radius.md,
            borderWidth: 1, borderColor: attachOpen ? t.accent : t.divider,
            alignItems: 'center', justifyContent: 'center',
          }}
        >
          <Animated.Text style={{ fontSize: 20, color: t.accent, transform: [{ rotate }] }}>+</Animated.Text>
        </Pressable>

        <TextInput
          value={text}
          onChangeText={onChangeText}
          onFocus={onFocus}
          onBlur={onBlur}
          placeholder="Ask about your books"
          placeholderTextColor="rgba(32,30,29,0.65)"
          cursorColor={t.accent}
          selectionColor={t.accent}
          style={{
            flex: 1,
            minHeight: 38,
            borderRadius: 19,
            paddingVertical: 8,
            paddingHorizontal: 14,
            fontFamily: t.fontBody,
            fontSize: 15,
            color: t.text,
            backgroundColor: t.surface,
            borderWidth: 1,
            borderColor: t.divider,
          }}
        />

        <Pressable
          onPress={onSend}
          style={({ pressed }) => ({
            width: 38, height: 38, borderRadius: 19,
            backgroundColor: pressed ? t.accentRamp[700] : t.accent,
            alignItems: 'center', justifyContent: 'center',
          })}
        >
          <Text style={{ fontSize: 17, color: t.bg }}>↑</Text>
        </Pressable>
      </View>
    </View>
  );
}

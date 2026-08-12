import { useRef, useState } from 'react';
import { View, Text, ScrollView, TextInput, Pressable, KeyboardAvoidingView, Platform, Modal } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTheme } from '../theme';
import { Avatar, Icon } from '../components';
import { UserMessage } from '../components/chat/UserMessage';
import { AssistantMessage } from '../components/chat/AssistantMessage';

const ATTACH_DRAWER_OPTIONS = [
  { key: 'camera', icon: 'camera', label: 'Camera' },
  { key: 'photos', icon: 'photos', label: 'Photos' },
  { key: 'files', icon: 'files', label: 'Files' },
];

let turnId = 1;

export default function ChatScreen() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const scrollRef = useRef(null);
  const turnOffsets = useRef({});

  const [composerText, setComposerText] = useState('');
  const [isComposerFocused, setIsComposerFocused] = useState(false);
  const [conversationTurns, setConversationTurns] = useState([]);
  const [scrollViewportHeight, setScrollViewportHeight] = useState(0);
  const [isAttachDrawerOpen, setIsAttachDrawerOpen] = useState(false);

  const send = () => {
    if (!composerText.trim()) return;
    const id = turnId++;
    setConversationTurns((prev) => [...prev, { id, question: composerText.trim(), answer: null }]);
    setComposerText('');
    setTimeout(() => {
      setConversationTurns((prev) => prev.map((tn) => (
        tn.id === id ? { ...tn, answer: 'Not wired up to real data yet — placeholder response.' } : tn
      )));
    }, 600);
  };

  const handleTurnLayout = (id, y) => {
    turnOffsets.current[id] = y;
    const latest = conversationTurns[conversationTurns.length - 1];
    if (latest && latest.id === id) {
      scrollRef.current?.scrollTo({ y, animated: true });
    }
  };

  return (
    <View style={{ flex: 1, backgroundColor: t.bg }}>
      <View style={{
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        paddingTop: insets.top + 12,
        paddingHorizontal: 20,
        paddingBottom: 10,
      }}>
        <View style={{
          width: 28, height: 28, borderRadius: 14,
          borderWidth: 1, borderColor: t.divider,
          alignItems: 'center', justifyContent: 'center',
        }}>
          <Text style={{ fontFamily: t.fontHeading, fontWeight: '600', fontSize: 11 }}>
            <Text style={{ color: t.accent }}>B</Text>
            <Text style={{ color: t.accent2 }}>A</Text>
          </Text>
        </View>

        <Avatar initials="SL" />
      </View>

      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={{ flex: 1 }}>
          <ScrollView
            ref={scrollRef}
            style={{ flex: 1 }}
            contentContainerStyle={{ paddingHorizontal: 20, paddingTop: 4, paddingBottom: 20, gap: 24 }}
            onLayout={(e) => setScrollViewportHeight(e.nativeEvent.layout.height)}
          >
            {conversationTurns.map((turn) => (
              <View
                key={turn.id}
                onLayout={(e) => handleTurnLayout(turn.id, e.nativeEvent.layout.y)}
                style={{ gap: 10 }}
              >
                <UserMessage text={turn.question} />
                <AssistantMessage text={turn.answer ?? '…'} />
              </View>
            ))}
            {/* Reserves scroll room so the latest turn can always be pushed to the
                very top of the viewport, even when there isn't enough real content
                below it yet — without this, ScrollView clamps to its natural end
                and the latest turn lands at the bottom instead. */}
            <View style={{ height: scrollViewportHeight }} />
          </ScrollView>

          <View style={{ paddingHorizontal: 20, paddingBottom: insets.bottom + 14 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <Pressable
                onPress={() => setIsAttachDrawerOpen(true)}
                style={{
                  width: 36, height: 36, borderRadius: t.radius.md,
                  borderWidth: 1, borderColor: t.divider,
                  alignItems: 'center', justifyContent: 'center',
                }}
              >
                <Text style={{ fontSize: 20, color: t.accent }}>+</Text>
              </Pressable>

              <TextInput
                value={composerText}
                onChangeText={setComposerText}
                onFocus={() => setIsComposerFocused(true)}
                onBlur={() => setIsComposerFocused(false)}
                autoFocus
                placeholder="How much did I spend on my groceries this week?"
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
                  borderColor: isComposerFocused ? t.accent : t.divider,
                }}
              />

              {composerText.length > 0 && (
                <Pressable
                  onPress={send}
                  style={{
                    width: 38, height: 38, borderRadius: 19,
                    backgroundColor: t.accent,
                    alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  <Text style={{ fontSize: 17, color: t.bg }}>↑</Text>
                </Pressable>
              )}
            </View>
          </View>
        </View>
      </KeyboardAvoidingView>

      <Modal
        visible={isAttachDrawerOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setIsAttachDrawerOpen(false)}
      >
        <View style={{ flex: 1 }}>
          <Pressable
            style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }}
            onPress={() => setIsAttachDrawerOpen(false)}
          />
          <View style={{
            position: 'absolute',
            left: 20,
            bottom: insets.bottom + 70,
            minWidth: 170,
            backgroundColor: t.bg,
            borderRadius: t.radius.lg,
            borderWidth: 1,
            borderColor: t.divider,
            paddingVertical: 4,
            ...t.shadowMd,
          }}>
            {ATTACH_DRAWER_OPTIONS.map((opt, i) => (
              <Pressable
                key={opt.key}
                onPress={() => setIsAttachDrawerOpen(false)}
                style={{
                  flexDirection: 'row',
                  alignItems: 'center',
                  gap: 10,
                  paddingVertical: 10,
                  paddingHorizontal: 14,
                  borderBottomWidth: i < ATTACH_DRAWER_OPTIONS.length - 1 ? 1 : 0,
                  borderBottomColor: t.rowHairline,
                }}
              >
                <Icon name={opt.icon} size={20} color={t.accent} />
                <Text style={{ fontFamily: t.fontBody, fontSize: 15, color: t.text }}>{opt.label}</Text>
              </Pressable>
            ))}
          </View>
        </View>
      </Modal>
    </View>
  );
}

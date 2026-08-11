import { useRef, useState } from 'react';
import { View, Text, ScrollView, KeyboardAvoidingView, Platform } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { router } from 'expo-router';
import { useTheme } from '../theme';
import { useLedger } from '../state/ledgerStore';
import { Avatar } from '../components';
import { AssistantMessage } from '../components/chat/AssistantMessage';
import { UserMessage } from '../components/chat/UserMessage';
import { PhotoMessage } from '../components/chat/PhotoMessage';
import { AnswerCard } from '../components/chat/AnswerCard';
import { DraftJournalCard } from '../components/chat/DraftJournalCard';
import { ChipList } from '../components/chat/ChipList';
import { Composer } from '../components/chat/Composer';
import { CameraOverlay } from '../components/chat/CameraOverlay';

const ANSWERS = {
  dining: {
    label: 'Dining · this week', value: '$182.40',
    note: '$41 more than your usual week — six visits instead of four.', link: '6 transactions',
    bars: [{ h: 44, tone: 200 }, { h: 61, tone: 200 }, { h: 38, tone: 200 }, { h: 72, tone: 200 }, { h: 100, tone: 500 }],
  },
  biggest: {
    label: 'Largest expense · August', value: '$2,150.00',
    note: 'Rent, posted 1 Aug. Next largest is $486 of software.', link: 'Open entry',
    bars: [{ h: 100, tone: 500 }, { h: 23, tone: 200 }, { h: 19, tone: 200 }, { h: 14, tone: 200 }, { h: 9, tone: 200 }],
  },
  usual: {
    label: 'Total spend · August to date', value: '$4,318.90',
    note: 'Running 8% under the same ten days last month. Dining is the only line up.', link: '38 transactions',
    bars: [{ h: 70, tone: 200 }, { h: 88, tone: 200 }, { h: 64, tone: 200 }, { h: 92, tone: 200 }, { h: 76, tone: 500 }],
  },
};

const CHIPS = [
  ['How much did I spend on dining this week?', 'dining'],
  ["What's my biggest expense this month?", 'biggest'],
  ['Am I spending more than usual?', 'usual'],
];

let msgId = 1;

export default function ChatScreen() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const { addEntry } = useLedger();
  const scrollRef = useRef(null);

  const [msgs, setMsgs] = useState([
    { id: msgId, role: 'a', text: "Morning, Sangmin. Ask me anything about your books — or snap a receipt and I'll post it." },
  ]);
  const [text, setText] = useState('');
  const [camera, setCamera] = useState(false);
  const [attach, setAttach] = useState(false);
  const [staged, setStaged] = useState(false);
  const [draft, setDraft] = useState(null);

  const push = (m) => {
    msgId += 1;
    setMsgs((prev) => [...prev, { id: msgId, ...m }]);
  };

  const ask = (key, questionText) => {
    push({ role: 'u', text: questionText });
    setTimeout(() => push({ role: 'answer', ...ANSWERS[key] }), 320);
  };

  const send = () => {
    if (staged) {
      setStaged(false);
      setText('');
      setAttach(false);
      push({ role: 'photo' });
      setTimeout(() => {
        setDraft({ date: '10 Aug 2026', merchant: 'Blue Bottle', amount: '$18.40', category: 'Dining', memo: 'Coffee + pastry' });
      }, 500);
      return;
    }
    if (!text.trim()) return;
    const hit = CHIPS.find(([c]) => c.toLowerCase().slice(0, 14) === text.toLowerCase().slice(0, 14));
    const sent = text;
    setText('');
    if (hit) { ask(hit[1], sent); return; }
    push({ role: 'u', text: sent });
    setTimeout(() => push({ role: 'answer', ...ANSWERS.usual }), 320);
  };

  const confirmDraft = () => {
    addEntry({
      merchant: draft.merchant,
      amount: draft.amount,
      category: draft.category,
      date: draft.date.replace(' 2026', ''),
      memo: draft.memo,
    });
    const { amount, category, date } = draft;
    setDraft(null);
    setTimeout(() => push({ role: 'a', text: `Posted to the ledger — ${category}, ${amount}, ${date.replace(' 2026', '')}. Double-entry lines are recorded underneath.` }), 200);
  };

  const showChips = msgs.length === 1 && !draft;

  return (
    <View style={{ flex: 1, backgroundColor: t.bg }}>
      <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 10, paddingTop: insets.top + 12, paddingHorizontal: 20, paddingBottom: 10 }}>
        <Text style={{ fontFamily: t.fontHeading, fontWeight: '600', fontSize: 19, letterSpacing: -0.4, color: t.text, marginRight: 'auto' }}>
          BalanceAI
        </Text>
        <Avatar initials="SL" />
      </View>

      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView
          ref={scrollRef}
          style={{ flex: 1 }}
          contentContainerStyle={{ paddingHorizontal: 20, paddingTop: 4, paddingBottom: 12, gap: 22 }}
          onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: true })}
        >
          {msgs.map((m) => {
            if (m.role === 'a') return <AssistantMessage key={m.id} text={m.text} />;
            if (m.role === 'u') return <UserMessage key={m.id} text={m.text} />;
            if (m.role === 'photo') return <PhotoMessage key={m.id} />;
            if (m.role === 'answer') {
              return (
                <AnswerCard
                  key={m.id}
                  label={m.label}
                  value={m.value}
                  note={m.note}
                  bars={m.bars}
                  link={m.link}
                  onPressLink={() => router.navigate('/(tabs)/journal')}
                />
              );
            }
            return null;
          })}

          {showChips && (
            <ChipList chips={CHIPS.map(([chipText, key]) => ({ text: chipText, onPress: () => ask(key, chipText) }))} />
          )}

          {draft && (
            <DraftJournalCard
              intro={`Read it as ${draft.merchant}, ${draft.amount}. Check the details and I'll post it.`}
              fields={draft}
              onChangeField={(key, value) => setDraft((prev) => ({ ...prev, [key]: value }))}
              onConfirm={confirmDraft}
              onDiscard={() => setDraft(null)}
            />
          )}
        </ScrollView>

        <Composer
          text={text}
          onChangeText={setText}
          onSend={send}
          attachOpen={attach}
          onToggleAttach={() => setAttach((v) => !v)}
          onOpenCamera={() => { setCamera(true); setAttach(false); }}
          staged={staged}
          onUnstage={() => setStaged(false)}
        />
      </KeyboardAvoidingView>

      <CameraOverlay
        visible={camera}
        onClose={() => setCamera(false)}
        onShoot={() => { setCamera(false); setStaged(true); }}
      />
    </View>
  );
}

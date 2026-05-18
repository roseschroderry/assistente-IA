import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Animated,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View
} from "react-native";
import { StatusBar } from "expo-status-bar";
import * as Speech from "expo-speech";
import {
  AudioModule,
  RecordingPresets,
  setAudioModeAsync,
  useAudioRecorder,
  useAudioRecorderState
} from "expo-audio";

import { API_BASE_URL, APP_CHANNEL } from "./src/config";
import {
  decideBrowserApproval,
  getBootstrap,
  getBrainStatus,
  getBrowserApprovals,
  getBrowserStatus,
  getMobileStatus,
  openBrainResult,
  scanBrain,
  searchBrain,
  sendChat,
  sendNotification,
  transcribeAudio
} from "./src/api";

const quickCommands = [
  "Mostre o status do sistema.",
  "Crie uma lista de tarefas para hoje.",
  "Resuma o que voce consegue fazer no app mobile.",
  "Me ajude a planejar uma rotina produtiva."
];

const initialMessages = [
  {
    id: "welcome",
    sender: "Assistente",
    type: "assistant",
    text: "Assistente Elite mobile pronto. Escreva um comando ou use a aba Voz."
  }
];

function nowLabel() {
  return new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function voiceLabel(voice = {}) {
  const stt = voice.deepgram_configured ? "Deepgram" : "Backend";
  const tts = voice.elevenlabs_configured ? "ElevenLabs" : "Celular";
  return `${stt} + ${tts}`;
}

function compactPath(path = "") {
  if (!path) return "--";
  const clean = String(path);
  if (clean.length <= 58) return clean;
  return `...${clean.slice(-55)}`;
}

function formatDateLabel(value) {
  if (!value) return "--";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function kindLabel(kind = "") {
  const labels = {
    app: "App",
    code: "Codigo",
    document: "Doc",
    folder: "Pasta",
    pdf: "PDF",
    presentation: "Slide",
    script: "Script",
    spreadsheet: "Planilha",
    text: "Texto"
  };
  return labels[kind] || kind || "Item";
}

function impactLabel(impact = "") {
  const labels = {
    high: "Alto impacto",
    medium: "Impacto medio",
    low: "Baixo impacto"
  };
  return labels[impact] || impact || "Impacto";
}

function Hologram({ active, speaking }) {
  const pulse = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: active || speaking ? 620 : 1400, useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 0, duration: active || speaking ? 620 : 1400, useNativeDriver: true })
      ])
    );
    loop.start();
    return () => loop.stop();
  }, [active, speaking, pulse]);

  const scale = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.92, active || speaking ? 1.18 : 1.04] });
  const opacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.38, active || speaking ? 0.92 : 0.58] });

  return (
    <View style={styles.holoWrap}>
      <Animated.View style={[styles.holoAura, { opacity, transform: [{ scale }] }]} />
      <Animated.View style={[styles.holoRingLarge, { opacity, transform: [{ scale }] }]} />
      <View style={styles.holoRingSmall} />
      <View style={[styles.holoCore, active && styles.holoCoreActive, speaking && styles.holoCoreSpeaking]}>
        <View style={styles.holoDot} />
      </View>
      <View style={styles.holoBars}>
        {[0, 1, 2, 3, 4].map((item) => (
          <Animated.View
            key={item}
            style={[
              styles.holoBar,
              {
                opacity,
                transform: [
                  {
                    scaleY: pulse.interpolate({
                      inputRange: [0, 1],
                      outputRange: [0.45 + item * 0.08, active || speaking ? 1.2 - item * 0.08 : 0.75]
                    })
                  }
                ]
              }
            ]}
          />
        ))}
      </View>
    </View>
  );
}

function StatusTile({ label, value }) {
  return (
    <View style={styles.tile}>
      <Text style={styles.tileLabel}>{label}</Text>
      <Text style={styles.tileValue} numberOfLines={2}>{value || "--"}</Text>
    </View>
  );
}

function TabButton({ active, label, onPress }) {
  return (
    <Pressable onPress={onPress} style={[styles.tabButton, active && styles.tabButtonActive]}>
      <Text style={[styles.tabText, active && styles.tabTextActive]}>{label}</Text>
    </Pressable>
  );
}

function BrainResultCard({ item, onOpen }) {
  return (
    <View style={styles.resultCard}>
      <View style={styles.resultHeader}>
        <Text style={styles.resultTitle} numberOfLines={2}>{item.name || "Sem nome"}</Text>
        <Text style={styles.kindBadge}>{kindLabel(item.kind)}</Text>
      </View>
      <Text style={styles.resultPath} numberOfLines={2}>{compactPath(item.path)}</Text>
      <View style={styles.resultFooter}>
        <Text style={styles.resultMeta}>Score {item.score ?? "--"}</Text>
        <Pressable onPress={() => onOpen(item)} style={styles.smallActionButton}>
          <Text style={styles.smallActionText}>Abrir no PC</Text>
        </Pressable>
      </View>
    </View>
  );
}

function ApprovalCard({ approval, onReview }) {
  return (
    <View style={styles.approvalCard}>
      <View style={styles.resultHeader}>
        <Text style={styles.resultTitle} numberOfLines={2}>{approval.instruction || "Acao sem descricao"}</Text>
        <Text style={[styles.kindBadge, approval.impact === "high" && styles.highBadge]}>{impactLabel(approval.impact)}</Text>
      </View>
      <Text style={styles.resultPath} numberOfLines={1}>{approval.url || "Sem URL"}</Text>
      <Text style={styles.approvalReason} numberOfLines={3}>{approval.reason || "Aguardando decisao humana."}</Text>
      <View style={styles.resultFooter}>
        <Text style={styles.resultMeta}>{formatDateLabel(approval.created_at)}</Text>
        <Pressable onPress={() => onReview(approval)} style={styles.smallActionButton}>
          <Text style={styles.smallActionText}>Revisar</Text>
        </Pressable>
      </View>
    </View>
  );
}

export default function App() {
  const [tab, setTab] = useState("chat");
  const [messages, setMessages] = useState(initialMessages);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [bootstrap, setBootstrap] = useState(null);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [readResponses, setReadResponses] = useState(true);
  const [speaking, setSpeaking] = useState(false);
  const [transcript, setTranscript] = useState("Toque em Gravar e fale seu comando.");
  const [recordingBusy, setRecordingBusy] = useState(false);
  const [brainQuery, setBrainQuery] = useState("");
  const [brainResults, setBrainResults] = useState([]);
  const [brainBusy, setBrainBusy] = useState(false);
  const [brainMessage, setBrainMessage] = useState("");
  const [browserStatus, setBrowserStatus] = useState(null);
  const [approvals, setApprovals] = useState([]);
  const [approvalsBusy, setApprovalsBusy] = useState(false);
  const [approvalMessage, setApprovalMessage] = useState("");
  const [selectedApproval, setSelectedApproval] = useState(null);
  const [approvalNote, setApprovalNote] = useState("");
  const [approvalConfirmed, setApprovalConfirmed] = useState(false);
  const [decisionBusy, setDecisionBusy] = useState(false);

  const audioRecorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recorderState = useAudioRecorderState(audioRecorder);

  const connected = Boolean(status || bootstrap);
  const voice = status?.voice || bootstrap?.voice || {};
  const features = status?.features || bootstrap?.features || {};
  const brain = status?.brain || bootstrap?.brain || {};
  const browser = browserStatus || status?.browser || bootstrap?.browser || {};

  const headerLabel = useMemo(() => {
    if (!connected) return "Conectando";
    return `${bootstrap?.assistant?.model || status?.model || "modelo"} ativo`;
  }, [bootstrap, connected, status]);

  async function refresh() {
    try {
      const data = await getBootstrap();
      setBootstrap(data);
      const live = await getMobileStatus();
      setStatus(live);
      setBrowserStatus(live.browser || data.browser || null);
      setError("");
    } catch (err) {
      setError(err.message || "Falha ao conectar");
    }
  }

  useEffect(() => {
    refresh();
    refreshBrowserApprovals(false);
    const timer = setInterval(refresh, 20000);
    const approvalsTimer = setInterval(() => refreshBrowserApprovals(false), 12000);
    return () => {
      clearInterval(timer);
      clearInterval(approvalsTimer);
    };
  }, []);

  async function refreshBrainStatus() {
    try {
      const data = await getBrainStatus();
      setStatus((prev) => ({ ...(prev || {}), brain: data }));
      setBrainMessage(data.message || "");
      setError("");
    } catch (err) {
      setBrainMessage(err.message || "Falha ao consultar cerebro.");
      setError(err.message || "Falha ao consultar cerebro.");
    }
  }

  async function submitBrainSearch(text = brainQuery) {
    const query = text.trim();
    if (!query || brainBusy) return;
    setBrainBusy(true);
    setBrainMessage("Buscando no cerebro...");
    try {
      const data = await searchBrain(query, 12);
      const results = data.results || [];
      setBrainResults(results);
      setBrainMessage(results.length ? `${results.length} resultado(s) encontrado(s).` : "Nada encontrado no cerebro.");
      setError("");
    } catch (err) {
      const msg = err.message || "Falha ao buscar no cerebro.";
      setBrainMessage(msg);
      setError(msg);
    } finally {
      setBrainBusy(false);
    }
  }

  async function startBrainScan() {
    if (brainBusy) return;
    setBrainBusy(true);
    setBrainMessage("Iniciando reindexacao...");
    try {
      const data = await scanBrain();
      setStatus((prev) => ({ ...(prev || {}), brain: data }));
      setBrainMessage(data.message || "Reindexacao iniciada.");
      setError("");
    } catch (err) {
      const msg = err.message || "Falha ao iniciar reindexacao.";
      setBrainMessage(msg);
      setError(msg);
    } finally {
      setBrainBusy(false);
    }
  }

  async function openBrainItem(item) {
    if (!item || brainBusy) return;
    setBrainBusy(true);
    setBrainMessage(`Abrindo ${item.name || "item"} no computador...`);
    try {
      const data = await openBrainResult(item.path || item.name || brainQuery, item.kind || "");
      setBrainMessage(data.result || "Solicitacao enviada ao computador.");
      setError("");
    } catch (err) {
      const msg = err.message || "Falha ao abrir resultado.";
      setBrainMessage(msg);
      setError(msg);
    } finally {
      setBrainBusy(false);
    }
  }

  async function refreshBrowserApprovals(showBusy = true) {
    if (showBusy) setApprovalsBusy(true);
    try {
      const [browserData, approvalsData] = await Promise.all([
        getBrowserStatus(),
        getBrowserApprovals(20)
      ]);
      const pending = approvalsData.approvals || [];
      setBrowserStatus(browserData);
      setApprovals(pending);
      setApprovalMessage(pending.length ? `${pending.length} aprovacao(oes) pendente(s).` : "Nenhuma aprovacao pendente.");
      setError("");
    } catch (err) {
      const msg = err.message || "Falha ao consultar aprovacoes.";
      setApprovalMessage(msg);
      setError(msg);
    } finally {
      if (showBusy) setApprovalsBusy(false);
    }
  }

  function reviewApproval(approval) {
    setSelectedApproval(approval);
    setApprovalNote("");
    setApprovalConfirmed(false);
    setApprovalMessage("");
  }

  async function decideApproval(approved) {
    if (!selectedApproval || decisionBusy) return;
    if (approved && !approvalConfirmed) {
      setApprovalMessage("Confirme que revisou os detalhes antes de aprovar.");
      return;
    }
    setDecisionBusy(true);
    const baseNote = approved ? "Aprovado no mobile" : "Rejeitado no mobile";
    const note = approvalNote.trim() ? `${baseNote}: ${approvalNote.trim()}` : baseNote;
    try {
      const data = await decideBrowserApproval(selectedApproval.id, approved, note);
      setSelectedApproval(null);
      setApprovalConfirmed(false);
      setApprovalNote("");
      await refreshBrowserApprovals(false);
      setApprovalMessage(
        data.status === "not_found"
          ? "Essa aprovacao nao existe mais."
          : approved
            ? "Acao aprovada e enviada ao navegador."
            : "Acao rejeitada."
      );
      setError("");
    } catch (err) {
      const msg = err.message || "Falha ao decidir aprovacao.";
      setApprovalMessage(msg);
      setError(msg);
    } finally {
      setDecisionBusy(false);
    }
  }

  function addMessage(sender, text, type = "assistant") {
    const item = {
      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      sender,
      text,
      type,
      time: nowLabel()
    };
    setMessages((prev) => [...prev, item].slice(-60));
  }

  function speak(text) {
    if (!readResponses || !text) return;
    Speech.stop();
    setSpeaking(true);
    Speech.speak(text.slice(0, 1200), {
      language: "pt-BR",
      rate: 1.02,
      onDone: () => setSpeaking(false),
      onStopped: () => setSpeaking(false),
      onError: () => setSpeaking(false)
    });
  }

  async function submitMessage(text = input) {
    const message = text.trim();
    if (!message || busy) return;

    setInput("");
    setBusy(true);
    addMessage("Voce", message, "user");
    try {
      const data = await sendChat(message, Platform.OS);
      const answer = data.response || "Sem resposta do nucleo.";
      addMessage("Assistente", answer, "assistant");
      speak(answer);
      setError("");
    } catch (err) {
      const msg = err.message || "Falha ao enviar comando.";
      addMessage("Erro", msg, "error");
      setError(msg);
    } finally {
      setBusy(false);
    }
  }

  async function startRecording() {
    if (recordingBusy || busy) return;
    setRecordingBusy(true);
    try {
      const permission = await AudioModule.requestRecordingPermissionsAsync();
      if (!permission.granted) {
        setTranscript("Permissao de microfone negada.");
        return;
      }
      await setAudioModeAsync({
        allowsRecording: true,
        playsInSilentMode: true
      });
      await audioRecorder.prepareToRecordAsync();
      audioRecorder.record();
      setTranscript("Ouvindo...");
      setError("");
    } catch (err) {
      setTranscript("Nao consegui iniciar o microfone.");
      setError(err.message || "Microfone indisponivel");
    } finally {
      setRecordingBusy(false);
    }
  }

  async function stopRecording() {
    if (recordingBusy) return;
    setRecordingBusy(true);
    try {
      await audioRecorder.stop();
      const uri = audioRecorder.uri;
      if (!uri) {
        setTranscript("Audio vazio.");
        return;
      }
      setTranscript("Transcrevendo pelo backend...");
      const data = await transcribeAudio(uri);
      const text = (data.text || "").trim();
      setTranscript(text || data.error || "Nao ouvi nada claro.");
      if (data.ok && text) {
        await submitMessage(text);
      }
    } catch (err) {
      setTranscript("Falha ao transcrever audio.");
      setError(err.message || "Transcricao indisponivel");
    } finally {
      setRecordingBusy(false);
    }
  }

  async function notifyTest() {
    try {
      await sendNotification("Teste enviado pelo app mobile.");
      addMessage("Sistema", "Notificacao de teste registrada no backend.", "system");
    } catch (err) {
      setError(err.message || "Falha na notificacao.");
    }
  }

  const isRecording = recorderState.isRecording;

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="light" />
      <KeyboardAvoidingView style={styles.app} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={styles.header}>
          <View>
            <Text style={styles.brand}>Assistente Elite</Text>
            <Text style={styles.subtitle}>{headerLabel}</Text>
          </View>
          <Pressable onPress={refresh} style={styles.roundButton}>
            <Text style={styles.roundButtonText}>R</Text>
          </Pressable>
        </View>

        <View style={styles.statusStrip}>
          <View style={[styles.statusDot, connected && styles.statusDotOnline]} />
          <Text style={styles.statusText}>{connected ? "Gateway conectado" : "Sem conexao"}</Text>
          <Text style={styles.channel}>{APP_CHANNEL}</Text>
        </View>

        <View style={styles.tabs}>
          <TabButton active={tab === "chat"} label="Chat" onPress={() => setTab("chat")} />
          <TabButton active={tab === "voice"} label="Voz" onPress={() => setTab("voice")} />
          <TabButton active={tab === "brain"} label="Cerebro" onPress={() => setTab("brain")} />
          <TabButton active={tab === "approvals"} label="Aprov." onPress={() => setTab("approvals")} />
          <TabButton active={tab === "status"} label="Status" onPress={() => setTab("status")} />
        </View>

        {tab === "chat" && (
          <View style={styles.content}>
            <ScrollView style={styles.messages} contentContainerStyle={styles.messagesInner}>
              {messages.map((item) => (
                <View key={item.id} style={[styles.message, styles[`message_${item.type}`]]}>
                  <Text style={[styles.messageSender, item.type === "user" && styles.messageSenderUser]}>
                    {item.sender} {item.time ? `- ${item.time}` : ""}
                  </Text>
                  <Text style={[styles.messageText, item.type === "user" && styles.messageTextUser]}>{item.text}</Text>
                </View>
              ))}
            </ScrollView>

            <View style={styles.quickList}>
              {quickCommands.map((cmd) => (
                <Pressable key={cmd} onPress={() => submitMessage(cmd)} style={styles.quickButton}>
                  <Text style={styles.quickText}>{cmd}</Text>
                </Pressable>
              ))}
            </View>

            <View style={styles.composer}>
              <TextInput
                style={styles.input}
                value={input}
                onChangeText={setInput}
                placeholder="Digite seu comando..."
                placeholderTextColor="#777"
                multiline
              />
              <Pressable onPress={() => submitMessage()} disabled={busy} style={[styles.sendButton, busy && styles.disabled]}>
                <Text style={styles.sendText}>{busy ? "..." : "Enviar"}</Text>
              </Pressable>
            </View>
          </View>
        )}

        {tab === "voice" && (
          <ScrollView style={styles.content} contentContainerStyle={styles.voiceInner}>
            <Hologram active={isRecording || recordingBusy} speaking={speaking} />
            <Text style={styles.voiceTitle}>{isRecording ? "Estou ouvindo" : speaking ? "Falando resposta" : "Voz pronta"}</Text>
            <Text style={styles.voiceSubtitle}>{voiceLabel(voice)}</Text>
            <View style={styles.transcriptBox}>
              <Text style={styles.transcriptLabel}>Transcricao</Text>
              <Text style={styles.transcriptText}>{transcript}</Text>
            </View>

            <Pressable
              onPress={isRecording ? stopRecording : startRecording}
              disabled={recordingBusy || busy}
              style={[styles.recordButton, isRecording && styles.recordButtonActive, (recordingBusy || busy) && styles.disabled]}
            >
              <Text style={styles.recordText}>{isRecording ? "Parar e enviar" : "Gravar comando"}</Text>
            </Pressable>

            <View style={styles.switchRow}>
              <View>
                <Text style={styles.switchTitle}>Ler respostas</Text>
                <Text style={styles.switchHint}>Usa a voz nativa do celular.</Text>
              </View>
              <Switch value={readResponses} onValueChange={setReadResponses} />
            </View>
          </ScrollView>
        )}

        {tab === "brain" && (
          <View style={styles.content}>
            <View style={styles.panelHeader}>
              <View>
                <Text style={styles.panelTitle}>Cerebro local</Text>
                <Text style={styles.panelSubtitle}>{brain.running ? `Indexando ${brain.items || 0}` : `${brain.items || 0} itens indexados`}</Text>
              </View>
              <Pressable onPress={refreshBrainStatus} style={styles.iconButton}>
                <Text style={styles.iconButtonText}>R</Text>
              </Pressable>
            </View>

            <View style={styles.searchBox}>
              <TextInput
                style={styles.searchInput}
                value={brainQuery}
                onChangeText={setBrainQuery}
                placeholder="Buscar arquivo, app, pasta..."
                placeholderTextColor="#777"
                returnKeyType="search"
                onSubmitEditing={() => submitBrainSearch()}
              />
              <Pressable onPress={() => submitBrainSearch()} disabled={brainBusy || !brainQuery.trim()} style={[styles.searchButton, (brainBusy || !brainQuery.trim()) && styles.disabled]}>
                <Text style={styles.searchButtonText}>{brainBusy ? "..." : "Buscar"}</Text>
              </Pressable>
            </View>

            <View style={styles.actionRow}>
              <Pressable onPress={startBrainScan} disabled={brainBusy} style={[styles.secondaryButtonCompact, brainBusy && styles.disabled]}>
                <Text style={styles.secondaryText}>Reindexar</Text>
              </Pressable>
            </View>

            {!!brainMessage && (
              <View style={styles.feedbackBox}>
                <Text style={styles.feedbackText}>{brainMessage}</Text>
              </View>
            )}

            <ScrollView style={styles.listSurface} contentContainerStyle={styles.listInner}>
              {brainResults.length === 0 ? (
                <Text style={styles.emptyText}>Digite uma busca para ver resultados do cerebro.</Text>
              ) : (
                brainResults.map((item) => (
                  <BrainResultCard key={`${item.id}-${item.path}`} item={item} onOpen={openBrainItem} />
                ))
              )}
            </ScrollView>
          </View>
        )}

        {tab === "approvals" && (
          <View style={styles.content}>
            <View style={styles.panelHeader}>
              <View>
                <Text style={styles.panelTitle}>Navegador operacional</Text>
                <Text style={styles.panelSubtitle}>
                  {(browser.provider || "local-fetch")} | {browser.pending_approvals || approvals.length || 0} pendente(s)
                </Text>
              </View>
              <Pressable onPress={() => refreshBrowserApprovals(true)} disabled={approvalsBusy} style={[styles.iconButton, approvalsBusy && styles.disabled]}>
                <Text style={styles.iconButtonText}>R</Text>
              </Pressable>
            </View>

            {!!approvalMessage && (
              <View style={styles.feedbackBox}>
                <Text style={styles.feedbackText}>{approvalMessage}</Text>
              </View>
            )}

            <ScrollView style={styles.listSurface} contentContainerStyle={styles.listInner}>
              {approvals.length === 0 ? (
                <Text style={styles.emptyText}>{approvalsBusy ? "Consultando aprovacoes..." : "Nenhuma acao pendente."}</Text>
              ) : (
                approvals.map((approval) => (
                  <ApprovalCard key={approval.id} approval={approval} onReview={reviewApproval} />
                ))
              )}
            </ScrollView>
          </View>
        )}

        {tab === "status" && (
          <ScrollView style={styles.content} contentContainerStyle={styles.statusInner}>
            <View style={styles.tileGrid}>
              <StatusTile label="API" value={API_BASE_URL} />
              <StatusTile label="Modelo" value={bootstrap?.assistant?.model || status?.model} />
              <StatusTile label="Ferramentas" value={String(bootstrap?.assistant?.tools || status?.tools || "--")} />
              <StatusTile label="Cerebro" value={brain.running ? "Indexando" : `${brain.items || 0} itens`} />
              <StatusTile label="Voz" value={voiceLabel(voice)} />
              <StatusTile label="Aprovacoes" value={`${browser.pending_approvals || approvals.length || 0} pendente(s)`} />
              <StatusTile label="Recursos" value={features.operator_tools ? "Operador ativo" : "Modo cliente"} />
            </View>
            <Pressable onPress={notifyTest} style={styles.secondaryButton}>
              <Text style={styles.secondaryText}>Enviar notificacao de teste</Text>
            </Pressable>
            <View style={styles.infoBox}>
              <Text style={styles.infoTitle}>Configuracao integrada</Text>
              <Text style={styles.infoText}>
                Este app vem apontado para o gateway do Assistente. As chaves de IA ficam no backend, nao no celular do cliente.
              </Text>
            </View>
          </ScrollView>
        )}

        <Modal
          transparent
          animationType="fade"
          visible={Boolean(selectedApproval)}
          onRequestClose={() => !decisionBusy && setSelectedApproval(null)}
        >
          <View style={styles.modalOverlay}>
            <View style={styles.modalSheet}>
              <ScrollView contentContainerStyle={styles.modalContent}>
                <View style={styles.resultHeader}>
                  <Text style={styles.modalTitle}>Revisar aprovacao</Text>
                  <Text style={[styles.kindBadge, selectedApproval?.impact === "high" && styles.highBadge]}>
                    {impactLabel(selectedApproval?.impact)}
                  </Text>
                </View>
                <Text style={styles.detailLabel}>Instrucao</Text>
                <Text style={styles.detailText}>{selectedApproval?.instruction || "--"}</Text>
                <Text style={styles.detailLabel}>URL</Text>
                <Text style={styles.detailText}>{selectedApproval?.url || "--"}</Text>
                <Text style={styles.detailLabel}>Motivo</Text>
                <Text style={styles.detailText}>{selectedApproval?.reason || "--"}</Text>
                <Text style={styles.detailLabel}>Criada em</Text>
                <Text style={styles.detailText}>{formatDateLabel(selectedApproval?.created_at)}</Text>

                <TextInput
                  style={styles.noteInput}
                  value={approvalNote}
                  onChangeText={setApprovalNote}
                  placeholder="Nota opcional da decisao"
                  placeholderTextColor="#777"
                  multiline
                />

                <View style={styles.confirmRow}>
                  <View style={styles.confirmCopy}>
                    <Text style={styles.switchTitle}>Confirmar aprovacao</Text>
                    <Text style={styles.switchHint}>A aprovacao executa a acao preparada no computador.</Text>
                  </View>
                  <Switch value={approvalConfirmed} onValueChange={setApprovalConfirmed} />
                </View>

                <View style={styles.modalActions}>
                  <Pressable onPress={() => !decisionBusy && setSelectedApproval(null)} disabled={decisionBusy} style={[styles.modalButton, styles.modalButtonGhost, decisionBusy && styles.disabled]}>
                    <Text style={styles.modalButtonGhostText}>Fechar</Text>
                  </Pressable>
                  <Pressable onPress={() => decideApproval(false)} disabled={decisionBusy} style={[styles.modalButton, styles.rejectButton, decisionBusy && styles.disabled]}>
                    <Text style={styles.rejectButtonText}>{decisionBusy ? "..." : "Rejeitar"}</Text>
                  </Pressable>
                  <Pressable onPress={() => decideApproval(true)} disabled={decisionBusy || !approvalConfirmed} style={[styles.modalButton, styles.approveButton, (decisionBusy || !approvalConfirmed) && styles.disabled]}>
                    <Text style={styles.approveButtonText}>{decisionBusy ? "..." : "Aprovar"}</Text>
                  </Pressable>
                </View>
              </ScrollView>
            </View>
          </View>
        </Modal>

        {!!error && (
          <View style={styles.errorBar}>
            <Text style={styles.errorText}>{error}</Text>
          </View>
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: "#050505"
  },
  app: {
    flex: 1,
    paddingHorizontal: 16,
    paddingTop: 12,
    backgroundColor: "#050505"
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 12
  },
  brand: {
    color: "#f4f4f4",
    fontSize: 26,
    fontWeight: "800"
  },
  subtitle: {
    marginTop: 4,
    color: "#a6a6a6",
    fontSize: 13
  },
  roundButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: "#343434",
    backgroundColor: "#151515"
  },
  roundButtonText: {
    color: "#e9e9e9",
    fontSize: 22
  },
  statusStrip: {
    minHeight: 42,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 12,
    borderRadius: 8,
    backgroundColor: "#101010",
    borderWidth: 1,
    borderColor: "#282828"
  },
  statusDot: {
    width: 9,
    height: 9,
    borderRadius: 5,
    backgroundColor: "#666"
  },
  statusDotOnline: {
    backgroundColor: "#efefef"
  },
  statusText: {
    flex: 1,
    color: "#d8d8d8",
    fontSize: 13
  },
  channel: {
    color: "#8b8b8b",
    fontSize: 12,
    textTransform: "uppercase"
  },
  tabs: {
    flexDirection: "row",
    gap: 6,
    marginVertical: 12
  },
  tabButton: {
    flex: 1,
    minHeight: 44,
    paddingHorizontal: 4,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#2b2b2b",
    backgroundColor: "#111"
  },
  tabButtonActive: {
    backgroundColor: "#ededed",
    borderColor: "#ededed"
  },
  tabText: {
    color: "#b8b8b8",
    fontWeight: "700",
    fontSize: 12
  },
  tabTextActive: {
    color: "#050505"
  },
  content: {
    flex: 1
  },
  panelHeader: {
    minHeight: 68,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    padding: 14,
    borderRadius: 8,
    backgroundColor: "#101010",
    borderWidth: 1,
    borderColor: "#292929",
    marginBottom: 10
  },
  panelTitle: {
    color: "#f2f2f2",
    fontSize: 20,
    fontWeight: "900"
  },
  panelSubtitle: {
    color: "#939393",
    fontSize: 12,
    marginTop: 4
  },
  iconButton: {
    width: 42,
    height: 42,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: "#3a3a3a",
    backgroundColor: "#151515"
  },
  iconButtonText: {
    color: "#f2f2f2",
    fontSize: 18,
    fontWeight: "900"
  },
  searchBox: {
    flexDirection: "row",
    gap: 8,
    marginBottom: 10
  },
  searchInput: {
    flex: 1,
    minHeight: 50,
    color: "#f0f0f0",
    paddingHorizontal: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#333",
    backgroundColor: "#101010"
  },
  searchButton: {
    width: 86,
    minHeight: 50,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    backgroundColor: "#ededed"
  },
  searchButtonText: {
    color: "#050505",
    fontWeight: "900"
  },
  actionRow: {
    flexDirection: "row",
    gap: 8,
    marginBottom: 10
  },
  secondaryButtonCompact: {
    minHeight: 44,
    paddingHorizontal: 14,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#3a3a3a",
    backgroundColor: "#151515"
  },
  feedbackBox: {
    padding: 11,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#2d3630",
    backgroundColor: "#101613",
    marginBottom: 10
  },
  feedbackText: {
    color: "#d8eadf",
    fontSize: 13,
    lineHeight: 18
  },
  listSurface: {
    flex: 1,
    borderRadius: 8,
    backgroundColor: "#0d0d0d",
    borderWidth: 1,
    borderColor: "#252525"
  },
  listInner: {
    padding: 10,
    gap: 10,
    paddingBottom: 18
  },
  emptyText: {
    color: "#8f8f8f",
    fontSize: 14,
    lineHeight: 20,
    padding: 12
  },
  resultCard: {
    padding: 12,
    borderRadius: 8,
    backgroundColor: "#151515",
    borderWidth: 1,
    borderColor: "#2e2e2e"
  },
  approvalCard: {
    padding: 12,
    borderRadius: 8,
    backgroundColor: "#151515",
    borderWidth: 1,
    borderColor: "#303030"
  },
  resultHeader: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 10
  },
  resultTitle: {
    flex: 1,
    color: "#f2f2f2",
    fontSize: 16,
    fontWeight: "900",
    lineHeight: 21
  },
  kindBadge: {
    maxWidth: 110,
    overflow: "hidden",
    color: "#050505",
    backgroundColor: "#dcdcdc",
    borderRadius: 8,
    paddingVertical: 5,
    paddingHorizontal: 8,
    fontSize: 11,
    fontWeight: "900",
    textTransform: "uppercase"
  },
  highBadge: {
    backgroundColor: "#f0c6c6",
    color: "#2a0505"
  },
  resultPath: {
    color: "#9a9a9a",
    marginTop: 8,
    fontSize: 12,
    lineHeight: 17
  },
  approvalReason: {
    color: "#c9c9c9",
    marginTop: 8,
    fontSize: 13,
    lineHeight: 18
  },
  resultFooter: {
    minHeight: 38,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    marginTop: 10
  },
  resultMeta: {
    flex: 1,
    color: "#7f7f7f",
    fontSize: 12
  },
  smallActionButton: {
    minHeight: 36,
    paddingHorizontal: 12,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    backgroundColor: "#ededed"
  },
  smallActionText: {
    color: "#050505",
    fontWeight: "900",
    fontSize: 12
  },
  messages: {
    flex: 1,
    minHeight: 260,
    borderRadius: 8,
    backgroundColor: "#0d0d0d",
    borderWidth: 1,
    borderColor: "#252525"
  },
  messagesInner: {
    padding: 12,
    gap: 10
  },
  message: {
    padding: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#2e2e2e",
    backgroundColor: "#151515"
  },
  message_user: {
    backgroundColor: "#ededed",
    borderColor: "#ededed"
  },
  message_assistant: {
    backgroundColor: "#151515"
  },
  message_error: {
    backgroundColor: "#221717",
    borderColor: "#4a3030"
  },
  message_system: {
    backgroundColor: "#101820",
    borderColor: "#26313b"
  },
  messageSender: {
    color: "#8f8f8f",
    fontSize: 11,
    fontWeight: "800",
    marginBottom: 6,
    textTransform: "uppercase"
  },
  messageSenderUser: {
    color: "#5c5c5c"
  },
  messageText: {
    color: "#e9e9e9",
    fontSize: 15,
    lineHeight: 21
  },
  messageTextUser: {
    color: "#050505"
  },
  quickList: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginVertical: 10
  },
  quickButton: {
    maxWidth: "48%",
    paddingVertical: 8,
    paddingHorizontal: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#2c2c2c",
    backgroundColor: "#111"
  },
  quickText: {
    color: "#d6d6d6",
    fontSize: 12,
    lineHeight: 16
  },
  composer: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 8,
    paddingBottom: 12
  },
  input: {
    flex: 1,
    minHeight: 50,
    maxHeight: 118,
    color: "#f0f0f0",
    padding: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#333",
    backgroundColor: "#101010"
  },
  sendButton: {
    width: 86,
    minHeight: 50,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#ededed"
  },
  sendText: {
    color: "#050505",
    fontWeight: "800"
  },
  voiceInner: {
    alignItems: "center",
    paddingBottom: 24
  },
  holoWrap: {
    width: 270,
    height: 270,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 16,
    marginBottom: 18
  },
  holoAura: {
    position: "absolute",
    width: 228,
    height: 228,
    borderRadius: 114,
    backgroundColor: "#303030"
  },
  holoRingLarge: {
    position: "absolute",
    width: 248,
    height: 96,
    borderRadius: 80,
    borderWidth: 2,
    borderColor: "#a6a6a6",
    transform: [{ rotate: "-10deg" }]
  },
  holoRingSmall: {
    position: "absolute",
    width: 180,
    height: 62,
    borderRadius: 60,
    borderWidth: 1,
    borderColor: "#747474",
    transform: [{ rotate: "14deg" }]
  },
  holoCore: {
    width: 126,
    height: 126,
    borderRadius: 63,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: "#d9d9d9",
    backgroundColor: "#161616"
  },
  holoCoreActive: {
    backgroundColor: "#202020"
  },
  holoCoreSpeaking: {
    backgroundColor: "#292929"
  },
  holoDot: {
    width: 42,
    height: 42,
    borderRadius: 21,
    backgroundColor: "#f2f2f2"
  },
  holoBars: {
    position: "absolute",
    bottom: 28,
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 7
  },
  holoBar: {
    width: 6,
    height: 42,
    borderRadius: 4,
    backgroundColor: "#f1f1f1"
  },
  voiceTitle: {
    color: "#f2f2f2",
    fontSize: 24,
    fontWeight: "800"
  },
  voiceSubtitle: {
    color: "#9b9b9b",
    marginTop: 6,
    marginBottom: 16
  },
  transcriptBox: {
    width: "100%",
    minHeight: 120,
    padding: 14,
    borderRadius: 8,
    backgroundColor: "#101010",
    borderWidth: 1,
    borderColor: "#292929"
  },
  transcriptLabel: {
    color: "#848484",
    fontSize: 12,
    fontWeight: "800",
    textTransform: "uppercase",
    marginBottom: 8
  },
  transcriptText: {
    color: "#e5e5e5",
    fontSize: 16,
    lineHeight: 23
  },
  recordButton: {
    width: "100%",
    minHeight: 56,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    backgroundColor: "#ededed",
    marginTop: 14
  },
  recordButtonActive: {
    backgroundColor: "#bfbfbf"
  },
  recordText: {
    color: "#050505",
    fontWeight: "900",
    fontSize: 16
  },
  switchRow: {
    width: "100%",
    minHeight: 72,
    marginTop: 12,
    padding: 14,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#292929",
    backgroundColor: "#0f0f0f",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between"
  },
  switchTitle: {
    color: "#e8e8e8",
    fontWeight: "800"
  },
  switchHint: {
    color: "#8a8a8a",
    marginTop: 4,
    fontSize: 12
  },
  statusInner: {
    paddingBottom: 22
  },
  tileGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10
  },
  tile: {
    width: "48%",
    minHeight: 92,
    padding: 12,
    borderRadius: 8,
    backgroundColor: "#101010",
    borderWidth: 1,
    borderColor: "#292929"
  },
  tileLabel: {
    color: "#808080",
    fontSize: 11,
    fontWeight: "800",
    textTransform: "uppercase"
  },
  tileValue: {
    color: "#f0f0f0",
    fontSize: 16,
    fontWeight: "800",
    marginTop: 10
  },
  secondaryButton: {
    minHeight: 50,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#3a3a3a",
    marginTop: 14,
    backgroundColor: "#151515"
  },
  secondaryText: {
    color: "#f2f2f2",
    fontWeight: "800"
  },
  infoBox: {
    marginTop: 14,
    padding: 14,
    borderRadius: 8,
    backgroundColor: "#0f0f0f",
    borderWidth: 1,
    borderColor: "#2b2b2b"
  },
  infoTitle: {
    color: "#f2f2f2",
    fontWeight: "900",
    fontSize: 16,
    marginBottom: 8
  },
  infoText: {
    color: "#a5a5a5",
    lineHeight: 20
  },
  modalOverlay: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 18,
    backgroundColor: "rgba(0,0,0,0.72)"
  },
  modalSheet: {
    width: "100%",
    maxHeight: "88%",
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#343434",
    backgroundColor: "#101010"
  },
  modalContent: {
    padding: 16,
    gap: 10
  },
  modalTitle: {
    flex: 1,
    color: "#f2f2f2",
    fontSize: 20,
    fontWeight: "900"
  },
  detailLabel: {
    color: "#818181",
    fontSize: 11,
    fontWeight: "900",
    textTransform: "uppercase"
  },
  detailText: {
    color: "#e7e7e7",
    fontSize: 14,
    lineHeight: 20
  },
  noteInput: {
    minHeight: 76,
    color: "#f0f0f0",
    textAlignVertical: "top",
    padding: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#333",
    backgroundColor: "#0b0b0b"
  },
  confirmRow: {
    minHeight: 74,
    padding: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#2e2e2e",
    backgroundColor: "#151515",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10
  },
  confirmCopy: {
    flex: 1
  },
  modalActions: {
    flexDirection: "row",
    gap: 8,
    marginTop: 2
  },
  modalButton: {
    flex: 1,
    minHeight: 46,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8
  },
  modalButtonGhost: {
    borderWidth: 1,
    borderColor: "#3a3a3a",
    backgroundColor: "#151515"
  },
  modalButtonGhostText: {
    color: "#f2f2f2",
    fontWeight: "900"
  },
  rejectButton: {
    backgroundColor: "#2a1515",
    borderWidth: 1,
    borderColor: "#5b2e2e"
  },
  rejectButtonText: {
    color: "#f0c9c9",
    fontWeight: "900"
  },
  approveButton: {
    backgroundColor: "#ededed"
  },
  approveButtonText: {
    color: "#050505",
    fontWeight: "900"
  },
  errorBar: {
    marginBottom: 10,
    padding: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#4a3030",
    backgroundColor: "#201414"
  },
  errorText: {
    color: "#f0c9c9"
  },
  disabled: {
    opacity: 0.55
  }
});

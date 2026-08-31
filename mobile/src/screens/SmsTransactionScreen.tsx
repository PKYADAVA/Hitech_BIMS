import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useQuery } from "@tanstack/react-query";
import React, { useLayoutEffect, useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";

import { listResource } from "@/api/resources";
import {
  fetchDocSources,
  fetchParties,
  fetchTransactionDocuments,
  previewTransactionDocument,
  sendTransactionDocument,
  SmsDocRow,
  SmsDocSource,
  SmsSentRecord,
  TransactionPreview,
} from "@/api/sms";
import { Row } from "@/api/types";
import { AppIcon } from "@/components/AppIcon";
import { DatePicker, toISODate } from "@/components/DatePicker";
import { Badge, BadgeTone, Card, EmptyOrError, Loading, Screen, SectionHeader } from "@/components/ui";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { makeStyles, radius, spacing, type, useTheme } from "@/theme";
import { confirm, notify } from "@/ui/confirm";
import { formatDate, formatMoney } from "@/utils/format";

type Props = NativeStackScreenProps<ModuleStackParams, "SmsTransaction">;

type Sheet = "docType" | "party" | "template" | "from" | "to" | null;

const rowKey = (r: SmsDocRow) => `${r.module}:${r.doc_id}`;

/** Successful sends of the CURRENTLY selected template for this document — mirrors
 *  the web page's sentForSelectedTemplate(), since "Sent" only means something
 *  relative to the template that is about to go out. */
function sentForTemplate(r: SmsDocRow, templateId: number | null): SmsSentRecord[] {
  if (!templateId) return [];
  return r.sent_history.filter((h) => String(h.template_id) === String(templateId));
}

function statusBadge(r: SmsDocRow, templateId: number | null): { label: string; tone: BadgeTone; caption?: string } {
  const mine = sentForTemplate(r, templateId);
  if (mine.length) {
    return { label: mine.length > 1 ? `Sent ×${mine.length}` : "Sent", tone: "success", caption: mine[0].sent_at };
  }
  if (r.sent_history.length) {
    return { label: templateId ? "Sent (other template)" : "Sent", tone: "info" };
  }
  return { label: "Not Sent", tone: "neutral" };
}

/**
 * Browse SMS-eligible documents across every registered source, pick a
 * template, multi-select, and send — the phone's version of the web SMS
 * Transaction page. Same filters (document type, party, date range,
 * template), same "already sent this template" awareness, same preview
 * before sending.
 */
export function SmsTransactionScreen({ navigation }: Props) {
  const { colors } = useTheme();
  const styles = useStyles();
  useLayoutEffect(() => navigation.setOptions({ title: "SMS Transaction" }), [navigation]);

  const today = toISODate(new Date());
  const [fromDate, setFromDate] = useState(today);
  const [toDate, setToDate] = useState(today);
  const [docKey, setDocKey] = useState(""); // "" = every document type
  const [partyId, setPartyId] = useState(""); // "" = every party of that type
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sheet, setSheet] = useState<Sheet>(null);
  const [sending, setSending] = useState(false);
  const [sendStatus, setSendStatus] = useState<
    { current: number; total: number; partyName: string; ok: number; failed: number; skipped: number } | null
  >(null);
  const [preview, setPreview] = useState<{ loading: boolean; items: TransactionPreview[] } | null>(null);

  const sourcesQ = useQuery({ queryKey: ["sms-doc-sources"], queryFn: fetchDocSources });
  const partiesQ = useQuery({ queryKey: ["sms-parties"], queryFn: fetchParties });
  const templatesQ = useQuery({
    queryKey: ["list", "/sms/templates/"],
    queryFn: () => listResource<Row>("/sms/templates/", { page_size: 200 }),
  });
  const docsQ = useQuery({
    queryKey: ["sms-transaction-documents", docKey, partyId, fromDate, toDate],
    queryFn: () =>
      fetchTransactionDocuments({
        module: docKey || undefined,
        party: docKey && partyId ? partyId : undefined,
        from_date: fromDate,
        to_date: toDate,
      }),
  });

  const sources = sourcesQ.data ?? [];
  const activeTemplates = (templatesQ.data?.items ?? []).filter((t) => !!t.is_active);
  const chosenSource = sources.find((s) => s.key === docKey);
  // "All" spans several party tables at once, so a single party id isn't
  // comparable across them — the party filter only applies to one document
  // type at a time, same as the web page.
  const partyGroup = chosenSource ? partiesQ.data?.[chosenSource.party_type] : undefined;
  const chosenParty = partyGroup?.options.find((p) => String(p.id) === partyId);

  // Same matching rule as the web page: a blank module/transaction on either
  // side means "generic — matches anything".
  const matchingTemplates = activeTemplates.filter((t) => {
    if (!chosenSource) return true;
    return (
      (!chosenSource.module || t.module === chosenSource.module) &&
      (!chosenSource.transaction || !t.transaction || t.transaction === chosenSource.transaction)
    );
  });
  const chosenTemplateRow = activeTemplates.find((t) => t.id === templateId);
  const chosenTemplate = chosenTemplateRow
    ? { id: chosenTemplateRow.id, name: String(chosenTemplateRow.name ?? "") }
    : undefined;

  const rows = docsQ.data ?? [];
  const selectableRows = rows.filter((r) => !!r.mobile);
  const allSelected = selectableRows.length > 0 && selectableRows.every((r) => selected.has(rowKey(r)));

  const toggleRow = (r: SmsDocRow) => {
    if (!r.mobile) return;
    setSelected((prev) => {
      const next = new Set(prev);
      const key = rowKey(r);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleAll = () => {
    setSelected((prev) => (allSelected ? new Set() : new Set(selectableRows.map(rowKey))));
  };

  // A template picked before switching document type may no longer match —
  // rather than silently keep an invalid choice, drop it so Send stays honest
  // about what it will actually use.
  const onPickDocType = (key: string) => {
    setDocKey(key);
    setPartyId("");
    setSelected(new Set());
    setSheet(null);
    if (templateId) {
      const src = sources.find((s) => s.key === key);
      const stillValid = activeTemplates.some(
        (t) =>
          t.id === templateId &&
          (!src || !src.module || t.module === src.module) &&
          (!src || !src.transaction || !t.transaction || t.transaction === src.transaction)
      );
      if (!stillValid) setTemplateId(null);
    }
  };

  const requireSelection = (): SmsDocRow[] | null => {
    if (!chosenTemplate) {
      notify("Choose a template", "Select a template first.");
      return null;
    }
    const targets = rows.filter((r) => selected.has(rowKey(r)));
    if (targets.length === 0) {
      notify("Nothing selected", "Select at least one record.");
      return null;
    }
    return targets;
  };

  const runPreview = async (targets: SmsDocRow[]) => {
    if (!chosenTemplate) return;
    setPreview({ loading: true, items: [] });
    const items: TransactionPreview[] = [];
    for (const r of targets) {
      try {
        items.push(
          await previewTransactionDocument({ module: r.module, doc_id: r.doc_id, template_id: chosenTemplate.id })
        );
      } catch (e) {
        items.push({
          party_name: r.party_name, mobile: r.mobile, doc_no: r.doc_no,
          message: `Could not render: ${(e as Error)?.message ?? "unknown error"}`,
          char_count: 0, sms_parts: 0, is_unicode: false,
        });
      }
    }
    setPreview({ loading: false, items });
  };

  const previewSelected = async () => {
    const targets = requireSelection();
    if (targets) runPreview(targets);
  };

  const previewRow = async (r: SmsDocRow) => {
    if (!chosenTemplate) return notify("Choose a template", "Select a template first.");
    runPreview([r]);
  };

  const onSend = async () => {
    let targets = requireSelection();
    if (!targets || !chosenTemplate) return;

    // Upfront awareness: some selected documents may already have received
    // THIS template successfully — offer to send again or skip them, the
    // same choice the web page's bulk-send offers before it starts.
    const already = targets.filter((r) => sentForTemplate(r, chosenTemplate.id).length);
    if (already.length) {
      const names = already.slice(0, 5).map((r) => r.doc_no).join(", ");
      const sendAgain = await confirm({
        title: "Already sent",
        message: `${already.length} of the selected already received this template successfully (${names}${
          already.length > 5 ? ", …" : ""
        }).`,
        confirmLabel: "Send Again",
        cancelLabel: "Skip Them",
      });
      if (!sendAgain) {
        targets = targets.filter((r) => !sentForTemplate(r, chosenTemplate.id).length);
        if (targets.length === 0) {
          notify("Nothing to send", "All selected documents already received this SMS.");
          return;
        }
      }
    }

    const ok = await confirm({
      title: "Send SMS",
      message: `Send "${chosenTemplate.name}" to ${targets.length} recipient(s)?`,
      confirmLabel: "Send",
    });
    if (!ok) return;

    setSending(true);
    let sent = 0, failed = 0, skipped = 0;
    try {
      for (let i = 0; i < targets.length; i++) {
        const r = targets[i];
        setSendStatus({ current: i + 1, total: targets.length, partyName: r.party_name, ok: sent, failed, skipped });
        try {
          let res = await sendTransactionDocument({
            module: r.module, doc_id: r.doc_id, template_id: chosenTemplate.id,
          });
          if (res.duplicate) {
            const again = await confirm({
              title: "Already sent",
              message: `${r.party_name} (${r.doc_no}): ${res.error ?? "This SMS was already sent recently."}`,
              confirmLabel: "Send Again",
              cancelLabel: "Skip",
            });
            if (again) {
              res = await sendTransactionDocument({
                module: r.module, doc_id: r.doc_id, template_id: chosenTemplate.id, force: true,
              });
            } else {
              skipped++;
              continue;
            }
          }
          if (res.sent) sent++;
          else failed++;
        } catch {
          failed++;
        }
      }
    } finally {
      setSending(false);
      setSendStatus(null);
      setSelected(new Set());
      docsQ.refetch();
      queryClient.invalidateQueries({ queryKey: ["list", "/sms/messages/"] });
      queryClient.invalidateQueries({ queryKey: ["stats-overview"] });
    }
    const parts = [`Sent: ${sent}`];
    if (failed) parts.push(`Failed: ${failed}`);
    if (skipped) parts.push(`Skipped: ${skipped}`);
    notify(failed ? "Some messages failed" : "Done", parts.join("  ·  "));
  };

  return (
    <Screen edges={["top", "left", "right"]}>
      <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
        <Card style={styles.filterCard}>
          <PickerRow
            label="Document Type"
            value={chosenSource ? chosenSource.label : "All Documents"}
            onPress={() => setSheet("docType")}
          />
          {chosenSource ? (
            <PickerRow
              label={partyGroup?.label ?? "Party"}
              value={chosenParty ? chosenParty.name : `All ${partyGroup ? `${partyGroup.label}s` : "Parties"}`}
              onPress={() => setSheet("party")}
            />
          ) : null}
          <PickerRow
            label="Template"
            value={chosenTemplate ? chosenTemplate.name : "Select a template"}
            onPress={() => setSheet("template")}
          />
          <View style={styles.dateRow}>
            <PickerRow label="From" value={formatDate(fromDate)} onPress={() => setSheet("from")} flex />
            <PickerRow label="To" value={formatDate(toDate)} onPress={() => setSheet("to")} flex />
          </View>
        </Card>

        <SectionHeader
          title={`Documents (${rows.length} Record${rows.length === 1 ? "" : "s"})`}
          action={
            selectableRows.length > 0 ? (
              <Pressable style={styles.selectAll} onPress={toggleAll} hitSlop={8}>
                <AppIcon
                  name={allSelected ? "checkbox-marked" : "checkbox-blank-outline"}
                  size={20}
                  color={allSelected ? colors.tint : colors.textFaint}
                />
                <Text style={styles.selectAllText}>Select All</Text>
              </Pressable>
            ) : undefined
          }
        />

        {docsQ.isLoading ? (
          <Loading label="Loading documents…" />
        ) : docsQ.isError ? (
          <EmptyOrError
            icon="⚠️"
            message={(docsQ.error as Error)?.message ?? "Could not load documents."}
            onRetry={docsQ.refetch}
          />
        ) : rows.length === 0 ? (
          <EmptyOrError icon="💬" message="No documents in this range." />
        ) : (
          rows.map((r) => {
            const key = rowKey(r);
            const checked = selected.has(key);
            const badge = statusBadge(r, templateId);
            const source = sources.find((s) => s.key === r.module);
            return (
              <Card key={key} onPress={() => toggleRow(r)} style={styles.docCard}>
                <View style={styles.docRow}>
                  <AppIcon
                    name={
                      !r.mobile
                        ? "checkbox-blank-off-outline"
                        : checked
                        ? "checkbox-marked"
                        : "checkbox-blank-outline"
                    }
                    size={22}
                    color={!r.mobile ? colors.textFaint : checked ? colors.tint : colors.textFaint}
                  />
                  <View style={{ flex: 1 }}>
                    <View style={styles.docHead}>
                      <Text style={styles.docParty} numberOfLines={1}>{r.party_name}</Text>
                      <View style={{ alignItems: "flex-end" }}>
                        <Badge label={badge.label} tone={badge.tone} />
                        {badge.caption ? <Text style={styles.docSentAt}>{badge.caption}</Text> : null}
                      </View>
                    </View>
                    <Text style={styles.docMeta}>
                      {r.doc_no}  ·  {formatDate(r.date)}
                      {r.amount ? `  ·  ${formatMoney(r.amount)}` : ""}
                    </Text>
                    {!docKey && source ? (
                      <Text style={styles.docModule}>{source.label} · {r.party_type}</Text>
                    ) : null}
                    <View style={styles.docFooter}>
                      <Text style={r.mobile ? styles.docMobile : styles.docNoMobile}>
                        {r.mobile || "No mobile number"}
                      </Text>
                      <Pressable hitSlop={8} onPress={() => previewRow(r)}>
                        <AppIcon name="eye-outline" size={18} color={colors.textFaint} />
                      </Pressable>
                    </View>
                  </View>
                </View>
              </Card>
            );
          })
        )}
        <View style={{ height: spacing.xxl }} />
      </ScrollView>

      <View style={styles.bottomBar}>
        {sendStatus ? (
          <View style={{ flex: 1 }}>
            <Text style={styles.progressText} numberOfLines={1}>
              Sending {sendStatus.current} of {sendStatus.total} — {sendStatus.partyName}
            </Text>
            <Text style={styles.progressCounts}>
              OK {sendStatus.ok}  ·  Failed {sendStatus.failed}  ·  Skipped {sendStatus.skipped}
            </Text>
          </View>
        ) : (
          <>
            <View>
              <Text style={styles.bottomLabel}>Selected</Text>
              <Text style={styles.bottomCount}>{selected.size}</Text>
            </View>
            <View style={styles.bottomActions}>
              <Pressable
                style={[styles.previewBtn, (selected.size === 0 || !chosenTemplate) && styles.sendBtnDisabled]}
                disabled={selected.size === 0 || !chosenTemplate}
                onPress={previewSelected}
              >
                <AppIcon name="eye-outline" size={18} color={colors.tint} />
              </Pressable>
              <Pressable
                style={[
                  styles.sendBtn,
                  (selected.size === 0 || !chosenTemplate || sending) && styles.sendBtnDisabled,
                ]}
                disabled={selected.size === 0 || !chosenTemplate || sending}
                onPress={onSend}
              >
                <Text style={styles.sendBtnText}>{sending ? "Sending…" : `Send SMS (${selected.size})`}</Text>
              </Pressable>
            </View>
          </>
        )}
      </View>

      {sheet === "docType" ? (
        <OptionSheet
          title="Document Type"
          options={[{ id: "", name: "All Documents" }, ...sources.map((s) => ({ id: s.key, name: s.label }))]}
          value={docKey}
          onPick={onPickDocType}
          onClose={() => setSheet(null)}
        />
      ) : null}
      {sheet === "party" ? (
        <OptionSheet
          title={partyGroup?.label ?? "Party"}
          options={[
            { id: "", name: `All ${partyGroup ? `${partyGroup.label}s` : "Parties"}` },
            ...(partyGroup?.options ?? []).map((p) => ({ id: String(p.id), name: p.name })),
          ]}
          value={partyId}
          onPick={(v) => { setPartyId(v); setSelected(new Set()); setSheet(null); }}
          onClose={() => setSheet(null)}
        />
      ) : null}
      {sheet === "template" ? (
        <OptionSheet
          title="Template"
          options={matchingTemplates.map((t) => ({ id: String(t.id), name: String(t.name) }))}
          value={templateId ? String(templateId) : ""}
          onPick={(v) => { setTemplateId(v ? Number(v) : null); setSheet(null); }}
          onClose={() => setSheet(null)}
          emptyLabel="No active template matches this document type."
        />
      ) : null}
      {sheet === "from" || sheet === "to" ? (
        <Modal visible animationType="slide" transparent onRequestClose={() => setSheet(null)}>
          <View style={styles.dateModalWrap}>
            <View style={styles.dateModalSheet}>
              <View style={styles.sheetHead}>
                <Text style={styles.sheetTitle}>{sheet === "from" ? "From Date" : "To Date"}</Text>
                <Pressable onPress={() => setSheet(null)} hitSlop={8}>
                  <Text style={styles.sheetClose}>Close</Text>
                </Pressable>
              </View>
              <DatePicker
                value={sheet === "from" ? fromDate : toDate}
                maximumDate={new Date()}
                onPick={(iso) => {
                  if (iso) (sheet === "from" ? setFromDate : setToDate)(iso);
                  setSheet(null);
                }}
              />
            </View>
          </View>
        </Modal>
      ) : null}

      {preview ? (
        <Modal visible animationType="slide" onRequestClose={() => setPreview(null)}>
          <Screen edges={["top", "left", "right"]}>
            <View style={styles.sheetHead}>
              <Text style={styles.sheetTitle}>SMS Preview</Text>
              <Pressable onPress={() => setPreview(null)} hitSlop={8}>
                <Text style={styles.sheetClose}>Close</Text>
              </Pressable>
            </View>
            {preview.loading ? (
              <Loading label="Rendering…" />
            ) : (
              <ScrollView contentContainerStyle={{ padding: spacing.md }}>
                {preview.items.map((p, i) => (
                  <Card key={i} style={styles.previewCard}>
                    <View style={styles.docHead}>
                      <Text style={styles.docParty} numberOfLines={1}>{p.party_name} — {p.mobile}</Text>
                    </View>
                    <Text style={styles.docMeta}>
                      {p.doc_no}  ·  {p.char_count} chars  ·  {p.sms_parts} part{p.sms_parts === 1 ? "" : "s"}
                      {"  ·  "}{p.is_unicode ? "Unicode" : "GSM"}
                    </Text>
                    <Text style={styles.previewMessage}>{p.message}</Text>
                  </Card>
                ))}
              </ScrollView>
            )}
          </Screen>
        </Modal>
      ) : null}
    </Screen>
  );
}

function PickerRow({
  label, value, onPress, flex,
}: { label: string; value: string; onPress: () => void; flex?: boolean }) {
  const { colors } = useTheme();
  const styles = useStyles();
  return (
    <Pressable style={[styles.pickerRow, flex && { flex: 1 }]} onPress={onPress}>
      <Text style={styles.pickerLabel}>{label}</Text>
      <View style={styles.pickerValueRow}>
        <Text style={styles.pickerValue} numberOfLines={1}>{value}</Text>
        <AppIcon name="chevron-down" size={18} color={colors.textFaint} />
      </View>
    </Pressable>
  );
}

function OptionSheet({
  title, options, value, onPick, onClose, emptyLabel,
}: {
  title: string;
  options: { id: string; name: string }[];
  value: string;
  onPick: (id: string) => void;
  onClose: () => void;
  emptyLabel?: string;
}) {
  const { colors } = useTheme();
  const styles = useStyles();
  return (
    <Modal visible animationType="slide" onRequestClose={onClose}>
      <Screen edges={["top", "left", "right"]}>
        <View style={styles.sheetHead}>
          <Text style={styles.sheetTitle}>{title}</Text>
          <Pressable onPress={onClose} hitSlop={8}>
            <Text style={styles.sheetClose}>Close</Text>
          </Pressable>
        </View>
        <ScrollView>
          {options.length === 0 ? (
            <Text style={styles.sheetEmpty}>{emptyLabel ?? "Nothing to choose."}</Text>
          ) : (
            options.map((o) => (
              <Pressable key={o.id || "all"} style={styles.sheetRow} onPress={() => onPick(o.id)}>
                <Text style={styles.sheetRowText} numberOfLines={1}>{o.name}</Text>
                {value === o.id ? <AppIcon name="check" size={18} color={colors.tint} /> : null}
              </Pressable>
            ))
          )}
        </ScrollView>
      </Screen>
    </Modal>
  );
}

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md, paddingBottom: spacing.md },

  filterCard: { marginBottom: spacing.md, gap: 2 },
  dateRow: { flexDirection: "row", gap: spacing.md },
  pickerRow: { paddingVertical: spacing.sm },
  pickerLabel: { ...type.caption, color: colors.textMuted },
  pickerValueRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 2 },
  pickerValue: { ...type.body, color: colors.text, flex: 1 },

  selectAll: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  selectAllText: { ...type.label, color: colors.text },

  docCard: { marginBottom: spacing.sm, padding: spacing.md },
  docRow: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start" },
  docHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm, justifyContent: "space-between" },
  docParty: { ...type.title, color: colors.text, flexShrink: 1 },
  docMeta: { ...type.caption, color: colors.textMuted, marginTop: 2 },
  docModule: { ...type.caption, color: colors.textFaint, marginTop: 1, textTransform: "capitalize" },
  docSentAt: { ...type.caption, color: colors.textFaint, marginTop: 2 },
  docFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 2 },
  docMobile: { ...type.caption, color: colors.text },
  docNoMobile: { ...type.caption, color: colors.danger },

  bottomBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.surface,
  },
  bottomLabel: { ...type.caption, color: colors.textMuted },
  bottomCount: { ...type.h3, color: colors.text },
  bottomActions: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  previewBtn: {
    width: 44, height: 44, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  sendBtn: {
    backgroundColor: colors.tint,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
  },
  sendBtnDisabled: { opacity: 0.5 },
  sendBtnText: { ...type.title, color: "#fff" },
  progressText: { ...type.body, color: colors.text },
  progressCounts: { ...type.caption, color: colors.textMuted, marginTop: 2 },

  sheetHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  sheetTitle: { ...type.h3, color: colors.text },
  sheetClose: { ...type.title, color: colors.tint },
  sheetRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  sheetRowText: { ...type.body, color: colors.text, flex: 1, marginRight: spacing.sm },
  sheetEmpty: { ...type.body, color: colors.textFaint, padding: spacing.lg },

  dateModalWrap: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.3)" },
  dateModalSheet: { backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg },

  previewCard: { marginBottom: spacing.sm, padding: spacing.md },
  previewMessage: { ...type.body, color: colors.text, marginTop: spacing.xs, lineHeight: 20 },
}));

import SwiftUI

/// A local sample workspace. Nothing in this view uses a Companion, a paired
/// computer, the network, or the archives and queues on disk.
struct ReviewDemoView: View {
    private struct Sample: Identifiable {
        let id = UUID()
        let title: String
        let text: String
    }

    private enum Page: String, CaseIterable, Identifiable {
        case archive = "Archive", library = "Library", chat = "Chat"
        var id: Self { self }
    }

    @Environment(\.dismiss) private var dismiss
    @Environment(\.locale) private var interfaceLocale
    @State private var page = Page.library
    @State private var samples = [
        Sample(title: "Rain garden checklist", text: "Choose native plants, check drainage after rain, and spread mulch to retain moisture."),
        Sample(title: "Community workshop", text: "Bring a notebook and arrive ten minutes before the workshop begins.")
    ]
    @State private var draft = ""
    @State private var query = ""
    @State private var question = "How do I care for a rain garden?"
    @State private var asked = ""
    @State private var sources: [Sample] = []

    var body: some View {
        NavigationStack {
            VStack(spacing: 8) {
                Text("Sample workspace. Changes last until you close the demo.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Picker("Demo section", selection: $page) {
                    ForEach(Page.allCases) { Text(LocalizedStringKey($0.rawValue)).tag($0) }
                }
                .pickerStyle(.segmented)
                .padding(.bottom, 4)
                content
            }
            .padding(.horizontal)
            .navigationTitle(PhoneLanguage.text("知识秘书演示",in:interfaceLocale))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Close") { dismiss() } } }
        }
    }

    @ViewBuilder private var content: some View {
        switch page {
        case .archive:
            Form {
                Section("Note or link") {
                    TextEditor(text: $draft).frame(minHeight: 115).accessibilityLabel("Demo note")
                    Button("Save to demo library", action: save)
                        .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        case .library:
            List {
                TextField("Search sample records", text: $query)
                Section("Records") {
                    let matches = matching(query)
                    if matches.isEmpty { Text("No matching records").foregroundStyle(.secondary) }
                    ForEach(matches) { recordLink($0) }
                }
            }
        case .chat:
            Form {
                Section {
                    TextField("Ask the demo library", text: $question).onSubmit(ask)
                    Button("Ask", action: ask)
                        .disabled(question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                } footer: {
                    Text("The demo quotes matching records directly. No AI service is called.")
                }
                if !asked.isEmpty {
                    Section("Answer") {
                        Text(asked).font(.headline)
                        if let source = sources.first {
                            Text(source.text)
                        } else {
                            Text("No sample record matches that question.")
                        }
                    }
                    if !sources.isEmpty {
                        Section("Sources") { ForEach(sources) { recordLink($0) } }
                    }
                }
            }
        }
    }

    private func recordLink(_ sample: Sample) -> some View {
        NavigationLink(sample.title) {
            ScrollView {
                Text(sample.text).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading).padding()
            }
            .navigationTitle(sample.title)
        }
    }

    private func save() {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        let title = text.split(whereSeparator: \.isNewline).first.map { String($0.prefix(70)) } ?? text
        samples.insert(Sample(title: title, text: text), at: 0)
        draft = ""
        query = ""
        page = .library
    }

    private func matching(_ input: String) -> [Sample] {
        let terms = input.split(whereSeparator: \.isWhitespace).map(String.init)
        return samples.filter { sample in
            terms.allSatisfy { (sample.title + " " + sample.text).localizedCaseInsensitiveContains($0) }
        }
    }

    private func ask() {
        let value = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return }
        asked = value
        let terms = value.lowercased().split(whereSeparator: { !$0.isLetter && !$0.isNumber })
        let common: Set<Substring> = ["how", "do", "does", "the", "for", "what", "where", "when", "about", "with", "and", "should", "can"]
        let keywords = Set(terms.filter { $0.count >= 3 && !common.contains($0) })
        let scored = samples.compactMap { sample -> (Sample, Int)? in
            let words = Set((sample.title + " " + sample.text).lowercased()
                .split(whereSeparator: { !$0.isLetter && !$0.isNumber }))
            let score = keywords.intersection(words).count
            return score > 0 ? (sample, score) : nil
        }
        sources = scored.sorted { $0.1 > $1.1 }.map { $0.0 }
    }
}

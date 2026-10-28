"""Thin Tk presentation layer for the application service."""
import argparse
import json
import queue
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, simpledialog
from tkinter.scrolledtext import ScrolledText
from .application import ApplicationService
from .platform import HostPlatform


class Application:
    def __init__(self, root, data_dir):
        self.root = root
        self.service = ApplicationService(data_dir)
        self.store = self.service.store
        self.closed = self.closing = False
        self.permission_dialog = None
        self.offset = 0
        root.title('Black Lantern Mercy · v0.2 The Vessel')
        root.geometry('1000x760')
        style = ttk.Style(root)
        style.theme_use('clam')
        top = ttk.Frame(root, padding=8)
        top.pack(fill='x')
        ttk.Label(top, text='Conversation').pack(side='left')
        self.session = ttk.Combobox(top, state='readonly', width=48)
        self.session.pack(side='left', padx=8)
        self.session.bind('<<ComboboxSelected>>', self.select_session)
        self.new_button = ttk.Button(top, text='New conversation', command=self.new_session)
        self.new_button.pack(side='left')
        self.status = tk.StringVar(value=f"Recovered {len(self.service.profile.recovered)} interrupted turn(s).")
        ttk.Label(root, textvariable=self.status, wraplength=970, padding=8).pack(fill='x')
        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill='both', expand=True, padx=8)
        chat = ttk.Frame(self.tabs)
        self.tabs.add(chat, text='Conversation')
        self.transcript = ScrolledText(chat, state='disabled', bg='#17131e', fg='#eee5fa', wrap='word', font=('Segoe UI', 11))
        self.transcript.pack(fill='both', expand=True)
        bottom = ttk.Frame(chat, padding=8)
        bottom.pack(fill='x')
        self.entry = ttk.Entry(bottom)
        self.entry.pack(side='left', fill='x', expand=True)
        self.entry.bind('<Return>', lambda event: self.send())
        self.send_button = ttk.Button(bottom, text='Send', command=self.send)
        self.send_button.pack(side='left', padx=5)
        self.cancel_button = ttk.Button(bottom, text='Cancel', command=self.service.cancel)
        self.cancel_button.pack(side='left')
        memory = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(memory, text='Durable memory')
        ttk.Label(memory, text='Explicit notes only. Never enter secrets. Deletion does not erase backups or past conversation references.').pack(anchor='w')
        self.memory_list = ttk.Treeview(memory, columns=('content', 'source', 'created'), show='headings')
        for col, width in [('content', 520), ('source', 120), ('created', 220)]:
            self.memory_list.heading(col, text=col.title())
            self.memory_list.column(col, width=width)
        self.memory_list.pack(fill='both', expand=True)
        self.memory_list.bind('<Double-1>', lambda e: self.inspect_memory())
        self.link_note = tk.BooleanVar(value=False)
        ttk.Checkbutton(memory, text='Link new note to latest completed turn in this conversation', variable=self.link_note).pack(anchor='w')
        buttons = ttk.Frame(memory)
        buttons.pack(fill='x')
        for title, command in [('Add note', self.add_memory), ('Inspect selected', self.inspect_memory), ('Delete selected', self.delete_memory)]:
            ttk.Button(buttons, text=title, command=command).pack(side='left', padx=3)
        audit = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(audit, text='Audit')
        controls = ttk.Frame(audit)
        controls.pack(fill='x')
        ttk.Label(controls, text='Turn ID (blank = all)').pack(side='left')
        self.audit_filter = ttk.Entry(controls, width=38)
        self.audit_filter.pack(side='left', padx=5)
        ttk.Button(controls, text='Filter / refresh', command=self.reset_audit).pack(side='left')
        ttk.Button(controls, text='Latest turn', command=self.latest_audit).pack(side='left')
        ttk.Button(controls, text='Newer', command=lambda: self.page_audit(-100)).pack(side='left')
        ttk.Button(controls, text='Older', command=lambda: self.page_audit(100)).pack(side='left')
        self.audit_page = tk.StringVar()
        ttk.Label(audit, textvariable=self.audit_page).pack(anchor='w')
        self.debug = ScrolledText(audit, state='disabled', wrap='word')
        self.debug.pack(fill='both', expand=True)
        settings = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(settings, text='Provider / profile')
        self.fields = {}
        for row, (key, label) in enumerate([('provider', 'Provider'), ('model', 'Exact model name'), ('endpoint', 'Local endpoint'),
                                           ('generation_timeout', 'Generation deadline (seconds)'), ('status_timeout', 'Status deadline (seconds)')]):
            ttk.Label(settings, text=label).grid(row=row, column=0, sticky='w', pady=5)
            value = tk.StringVar(value=str(self.service.config[key]))
            self.fields[key] = value
            widget = ttk.Combobox(settings, textvariable=value, values=['mock', 'ollama'], state='readonly') if key == 'provider' else ttk.Entry(settings, textvariable=value, width=48)
            widget.grid(row=row, column=1, sticky='ew', padx=10)
        self.apply_button = ttk.Button(settings, text='Save / check provider / reload identity', command=self.apply)
        self.apply_button.grid(row=5, column=0, columnspan=2, pady=12)
        ttk.Label(settings, text='No cloud backend or automatic model downloads. Switching providers preserves this profile.\nGeneration deadlines include permission waits. Cancel stops provider work.').grid(row=6, column=0, columnspan=2, sticky='w')
        ttk.Label(settings, text=f'Profile: {self.service.profile.path}', wraplength=880).grid(row=7, column=0, columnspan=2, sticky='w', pady=12)
        ttk.Button(settings, text='Inspect identity', command=lambda: self.show_detail('Identity', self.service.profile.identity)).grid(row=8, column=0, sticky='w')
        ttk.Label(settings, text='To upgrade v0.1, use a COPY of its profile with --data-dir. Schema upgrades create a database backup.\nKeep Acceptance 001 frozen. Never open its original profile with this version.', wraplength=880).grid(row=9, column=0, columnspan=2, sticky='w', pady=12)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh()
        self.reload_history()
        self.poll_id = root.after(40, self.poll)
        self.service.check_status()
        self.update_controls()

    @property
    def busy(self):
        return self.service.busy

    def update_controls(self):
        state = 'disabled' if self.busy or self.closing else 'normal'
        for widget in (self.send_button, self.apply_button, self.new_button):
            widget.configure(state=state)
        self.session.configure(state='disabled' if self.busy else 'readonly')
        self.cancel_button.configure(state='normal' if self.busy else 'disabled')

    def append(self, text):
        self.transcript.configure(state='normal')
        self.transcript.insert('end', text)
        self.transcript.see('end')
        self.transcript.configure(state='disabled')

    def reload_history(self):
        self.transcript.configure(state='normal')
        self.transcript.delete('1.0', 'end')
        self.transcript.configure(state='disabled')
        for m in self.store.history(200, self.service.config['conversation_id']):
            state = '' if m['state'] == 'complete' else f" [{m['state']}]"
            self.append(f"{m['role'].title()}{state}: {m['content']}\n\n")

    def refresh(self):
        self.sessions = self.store.conversations()
        self.session['values'] = [f"{c['id']} · {c['title']}" for c in self.sessions]
        self.session.current(next(i for i, c in enumerate(self.sessions) if c['id'] == self.service.config['conversation_id']))
        self.memories = self.store.memories()
        for item in self.memory_list.get_children():
            self.memory_list.delete(item)
        for m in self.memories:
            self.memory_list.insert('', 'end', iid=str(m['id']), values=(m['content'], m['source_kind'], m['created']))
        self.refresh_audit()

    def select_session(self, event=None):
        try:
            self.service.select_conversation(self.sessions[self.session.current()]['id'])
            self.reload_history()
        except Exception as exc:
            messagebox.showerror('Conversation', str(exc))

    def new_session(self):
        title = simpledialog.askstring('New conversation', 'Conversation title:')
        if title:
            try:
                self.service.new_conversation(title)
                self.refresh()
                self.reload_history()
            except Exception as exc:
                messagebox.showerror('Conversation', str(exc))

    def apply(self):
        try:
            values = {key: var.get() for key, var in self.fields.items()}
            for key in ('generation_timeout', 'status_timeout'):
                values[key] = float(values[key])
            self.service.configure({**self.service.config, **values})
            self.service.check_status()
            self.status.set('Checking provider…')
            self.update_controls()
        except Exception as exc:
            messagebox.showerror('Configuration', str(exc))

    def send(self):
        if self.busy:
            return
        text = self.entry.get()
        try:
            self.service.send(text)
        except Exception as exc:
            messagebox.showerror('Cannot send', str(exc))
            return
        self.entry.delete(0, 'end')
        self.append(f'You: {text.strip()}\n\nMercy: ')
        self.status.set('Responding…')
        self.update_controls()

    def permission(self, request):
        if self.service.pending is not request:
            return
        dialog = tk.Toplevel(self.root)
        self.permission_dialog = dialog
        dialog.title('Mercy requests permission')
        dialog.transient(self.root)
        ttk.Label(dialog, text=f'{request.purpose}\nCapability: {request.capability}\nPermission: {request.permission}\nArguments: {{}}\nAllow this one execution?', padding=16).pack()
        def respond(allow):
            try:
                self.service.respond(request.id, allow)
            except Exception:
                pass  # Expiration/cancellation is already reported by the controller.
            dialog.destroy()
            self.permission_dialog = None
        self.deny_button = ttk.Button(dialog, text='Deny', command=lambda: respond(False))
        self.deny_button.pack(side='left', padx=16, pady=12)
        self.allow_button = ttk.Button(dialog, text='Allow once', command=lambda: respond(True))
        self.allow_button.pack(side='right', padx=16, pady=12)
        dialog.protocol('WM_DELETE_WINDOW', lambda: respond(False))
        self.deny_button.focus_set()

    def poll(self):
        try:
            for _ in range(100):
                kind, value = self.service.events.get_nowait()
                if kind == 'text':
                    self.append(value)
                elif kind == 'status':
                    self.status.set(value['detail'] + ' | ' + ', '.join(value['models']))
                elif kind == 'error':
                    self.status.set(value)
                elif kind == 'permission':
                    self.permission(value)
                elif kind == 'done':
                    self.reload_history()
                    self.refresh()
                    self.update_controls()
        except queue.Empty:
            pass
        if self.permission_dialog and self.service.pending is None:
            self.permission_dialog.destroy()
            self.permission_dialog = None
        if not self.closed:
            self.poll_id = self.root.after(40, self.poll)

    def add_memory(self):
        text = simpledialog.askstring('Durable memory', 'Explicit note (no secrets):')
        if text:
            try:
                source_kind, reference = 'user', None
                if self.link_note.get():
                    turns = [t for t in self.store.turns(self.service.config['conversation_id']) if t['state'] == 'complete']
                    if not turns:
                        raise ValueError('This conversation has no completed turn to link.')
                    source_kind, reference = 'conversation', turns[-1]['id']
                self.store.remember(text, source_kind, reference)
                self.refresh()
            except Exception as exc:
                messagebox.showerror('Memory', str(exc))

    def inspect_memory(self):
        selected = self.memory_list.selection()
        if selected:
            self.show_detail('Memory provenance', next(m for m in self.memories if str(m['id']) == selected[0]))

    def delete_memory(self):
        selected = self.memory_list.selection()
        if selected and messagebox.askyesno('Delete note', 'Delete this note from active memory? Past chats and backups are not erased.', default='no'):
            self.store.forget(int(selected[0]))
            self.refresh()

    def show_detail(self, title, value):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        text = ScrolledText(dialog, width=90, height=25, wrap='word')
        text.pack(fill='both', expand=True)
        text.insert('end', json.dumps(value, indent=2, ensure_ascii=False))
        text.configure(state='disabled')

    def reset_audit(self):
        self.offset = 0
        self.refresh_audit()

    def latest_audit(self):
        turns = self.store.turns(self.service.config['conversation_id'])
        self.audit_filter.delete(0, 'end')
        if turns:
            self.audit_filter.insert(0, turns[-1]['id'])
        self.reset_audit()

    def page_audit(self, delta):
        self.offset = max(0, self.offset + delta)
        self.refresh_audit()

    def refresh_audit(self):
        rows = self.store.audits(100, self.offset, self.audit_filter.get().strip() or None)
        self.audit_page.set(f'{len(rows)} records · offset {self.offset} · intent is not proof of execution')
        self.debug.configure(state='normal')
        self.debug.delete('1.0', 'end')
        for row in rows:
            row['data'] = json.loads(row['data'])
            self.debug.insert('end', json.dumps(row, indent=2) + '\n')
        self.debug.configure(state='disabled')

    def close(self):
        self.closing = True
        self.service.cancel()
        if not self.service.close(timeout=0):
            self.status.set('Cancelling and saving turn before closing…')
            self.root.after(50, self.close)
            return
        self.closed = True
        self.root.after_cancel(self.poll_id)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description='Black Lantern Mercy v0.2 — The Vessel')
    parser.add_argument('--data-dir', type=Path, help='Use a copied profile for migration. Never use frozen Acceptance 001.')
    args = parser.parse_args()
    root = tk.Tk()
    try:
        Application(root, args.data_dir or HostPlatform().data_dir())
    except Exception as exc:
        messagebox.showerror('Mercy could not start', str(exc))
        root.destroy()
        return
    root.mainloop()

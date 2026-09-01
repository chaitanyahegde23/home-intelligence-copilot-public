import {
  type ChangeEvent,
  type DragEvent,
  type FormEvent,
  useEffect,
  useRef,
  useState,
} from 'react'
import {
  formatBytes,
  ImportRequestError,
  type TransactionImportResponse,
  uploadTransactions,
  validateTransactionFile,
} from '../api/imports'
import { maxUploadSizeBytes } from '../api/config'

interface DisplayError {
  message: string
  canRetry: boolean
}

const statusContent = {
  completed: {
    eyebrow: 'Import complete',
    heading: 'Every transaction row was accepted.',
  },
  completed_with_errors: {
    eyebrow: 'Import partially complete',
    heading: 'Valid rows were saved; some rows need attention.',
  },
  failed: {
    eyebrow: 'Import failed',
    heading: 'No transaction rows were accepted.',
  },
  pending: {
    eyebrow: 'Import pending',
    heading: 'The import is waiting to be processed.',
  },
  processing: {
    eyebrow: 'Import processing',
    heading: 'The import is still being processed.',
  },
} as const

export function TransactionImport() {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [isOpen, setIsOpen] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [accountLabel, setAccountLabel] = useState('')
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState<DisplayError | null>(null)
  const [result, setResult] = useState<TransactionImportResponse | null>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (isOpen && !dialog.open) {
      if (typeof dialog.showModal === 'function') dialog.showModal()
      else dialog.setAttribute('open', '')
      fileInputRef.current?.focus()
    } else if (!isOpen && dialog.open) {
      if (typeof dialog.close === 'function') dialog.close()
      else dialog.removeAttribute('open')
    }
  }, [isOpen])

  const validateFile = (file: File | null) => {
    setSelectedFile(file)
    setResult(null)
    if (!file) {
      setError(null)
      return
    }
    const validationMessage = validateTransactionFile(file)
    setError(validationMessage ? { message: validationMessage, canRetry: false } : null)
  }

  const selectFile = (event: ChangeEvent<HTMLInputElement>) => {
    validateFile(event.currentTarget.files?.[0] ?? null)
  }

  const dropFile = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setIsDragging(false)
    if (!isUploading) validateFile(event.dataTransfer.files?.[0] ?? null)
  }

  const closeDialog = () => {
    if (isUploading) return
    setIsOpen(false)
    triggerRef.current?.focus()
  }

  useEffect(() => {
    if (!isOpen) return
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isUploading) {
        event.preventDefault()
        setIsOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [isOpen, isUploading])

  const runImport = async () => {
    if (!selectedFile) {
      setError({ message: 'Choose a CSV file before starting the import.', canRetry: false })
      fileInputRef.current?.focus()
      return
    }
    const validationMessage = validateTransactionFile(selectedFile)
    if (validationMessage) {
      setError({ message: validationMessage, canRetry: false })
      fileInputRef.current?.focus()
      return
    }

    setIsUploading(true)
    setError(null)
    setResult(null)
    try {
      const response = await uploadTransactions(selectedFile, accountLabel.trim() || undefined)
      setResult(response)
    } catch (requestError: unknown) {
      setError({
        message:
          requestError instanceof Error
            ? requestError.message
            : 'The import failed for an unexpected reason.',
        canRetry:
          requestError instanceof ImportRequestError &&
          ['network_error', 'server_error'].includes(requestError.code),
      })
    } finally {
      setIsUploading(false)
    }
  }

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void runImport()
  }

  const reset = () => {
    setSelectedFile(null)
    setAccountLabel('')
    setError(null)
    setResult(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
    fileInputRef.current?.focus()
  }

  return (
    <section className="import-section" id="imports" aria-labelledby="import-title">
      <div className="import-toolbar">
        <div>
          <p className="eyebrow">Transaction records</p>
          <h2 id="import-title">Imports</h2>
        </div>
        <button ref={triggerRef} type="button" onClick={() => setIsOpen(true)}>
          Import statement
        </button>
      </div>

      <dialog
        ref={dialogRef}
        className="import-dialog"
        aria-labelledby="import-dialog-title"
        onCancel={(event) => {
          if (isUploading) event.preventDefault()
        }}
        onClose={() => {
          setIsOpen(false)
          triggerRef.current?.focus()
        }}
      >
        <div className="dialog-heading">
          <div>
            <p className="eyebrow">Bring in transactions</p>
            <h2 id="import-dialog-title">Import a statement CSV</h2>
          </div>
          <button
            className="dialog-close"
            type="button"
            aria-label="Close import dialog"
            disabled={isUploading}
            onClick={closeDialog}
          >
            ×
          </button>
        </div>

        <form className="import-modal-form" onSubmit={submit} noValidate>
          <div className="field-group">
            <label htmlFor="transaction-file">Transaction CSV</label>
            <p id="file-guidance" className="field-guidance">
              CSV only, up to {formatBytes(maxUploadSizeBytes)}. Supported formats include the
              canonical sample and reviewed Citi, Chase, and Bank of America exports.
            </p>
            <div
              className={`file-drop-zone${isDragging ? ' file-drop-zone--active' : ''}`}
              onDragEnter={(event) => {
                event.preventDefault()
                if (!isUploading) setIsDragging(true)
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={() => setIsDragging(false)}
              onDrop={dropFile}
            >
              <input
                ref={fileInputRef}
                id="transaction-file"
                name="file"
                type="file"
                accept=".csv,text/csv,application/csv,application/vnd.ms-excel"
                aria-describedby="file-guidance selected-file"
                aria-invalid={Boolean(error && !error.canRetry)}
                disabled={isUploading}
                onChange={selectFile}
              />
              <span>or drag and drop a CSV here</span>
            </div>
            <p id="selected-file" className="selected-file" aria-live="polite">
              {selectedFile
                ? `${selectedFile.name} · ${formatBytes(selectedFile.size)}`
                : 'No file selected'}
            </p>
          </div>

          <div className="field-group">
            <label htmlFor="account-label">
              Account label <span>Optional</span>
            </label>
            <p id="account-guidance" className="field-guidance">
              Use a safe household label, not an account number. Existing row-level account names
              are preserved.
            </p>
            <input
              id="account-label"
              name="account_label"
              type="text"
              maxLength={255}
              value={accountLabel}
              aria-describedby="account-guidance"
              disabled={isUploading}
              onChange={(event) => setAccountLabel(event.currentTarget.value)}
              placeholder="Example: Household checking"
            />
          </div>

          <div className="upload-actions">
            <button type="submit" disabled={isUploading || Boolean(error && !error.canRetry)}>
              {isUploading ? 'Importing...' : 'Import transactions'}
            </button>
            {(selectedFile || result || error) && !isUploading && (
              <button className="button-secondary" type="button" onClick={reset}>
                Reset
              </button>
            )}
          </div>

          <p className="privacy-note">
            Your file is sent only to the API configured for this application. Do not upload real
            household data to an environment you do not control.
          </p>
        </form>

        {(isUploading || error || result) && (
          <div className="import-feedback">
            {isUploading && (
              <div className="import-progress" role="status" aria-live="polite">
                <progress aria-label="Uploading and validating CSV" />
                <p className="eyebrow">Import in progress</p>
                <h3>Uploading and validating rows...</h3>
                <p>The API will save valid rows atomically and return a reconciled result.</p>
              </div>
            )}

            {error && !isUploading && (
              <div className="import-error" role="alert">
                <p className="eyebrow">Import could not continue</p>
                <h3>Check the file and try again.</h3>
                <p>{error.message}</p>
                {error.canRetry && (
                  <button type="button" onClick={() => void runImport()}>
                    Retry import
                  </button>
                )}
              </div>
            )}

            {result && !isUploading && (
              <ImportResult result={result} onRetry={runImport} onReset={reset} />
            )}
          </div>
        )}
      </dialog>
    </section>
  )
}

interface ImportResultProps {
  result: TransactionImportResponse
  onRetry: () => Promise<void>
  onReset: () => void
}

function ImportResult({ result, onRetry, onReset }: ImportResultProps) {
  const content = statusContent[result.status]
  return (
    <section
      className={`import-result import-result--${result.status}`}
      aria-labelledby="import-result-title"
      aria-live="polite"
    >
      <p className="eyebrow">{content.eyebrow}</p>
      <h3 id="import-result-title">{content.heading}</h3>
      <p className="result-file">{result.filename}</p>

      <dl className="import-counts">
        <div>
          <dt>Total rows</dt>
          <dd>{result.total_rows}</dd>
        </div>
        <div>
          <dt>Imported</dt>
          <dd>{result.imported_rows}</dd>
        </div>
        <div>
          <dt>Rejected</dt>
          <dd>{result.rejected_rows}</dd>
        </div>
      </dl>

      <dl className="import-metadata">
        <div>
          <dt>Format</dt>
          <dd>
            {result.adapter_name} v{result.adapter_version}
          </dd>
        </div>
        <div>
          <dt>Account label</dt>
          <dd>{result.account_label ?? 'From source rows or adapter default'}</dd>
        </div>
        <div>
          <dt>Possible duplicates</dt>
          <dd>{result.duplicate_candidates_created}</dd>
        </div>
        <div>
          <dt>Import batch</dt>
          <dd className="batch-id">{result.import_batch_id}</dd>
        </div>
      </dl>

      {result.errors.length > 0 && (
        <div className="row-errors">
          <h4>Row validation errors</h4>
          <div className="row-error-table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Row</th>
                  <th scope="col">Field</th>
                  <th scope="col">Issue</th>
                </tr>
              </thead>
              <tbody>
                {result.errors.map((rowError, index) => (
                  <tr key={`${rowError.row_number}-${rowError.field}-${index}`}>
                    <td>{rowError.row_number ?? 'File'}</td>
                    <td>{rowError.field ?? 'General'}</td>
                    <td>{rowError.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="upload-actions">
        {result.status === 'failed' && (
          <button type="button" onClick={() => void onRetry()}>
            Retry same file
          </button>
        )}
        <button className="button-secondary" type="button" onClick={onReset}>
          Choose another file
        </button>
      </div>
    </section>
  )
}

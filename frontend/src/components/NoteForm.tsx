import { useTranslation } from 'react-i18next'
import { useCallback, useMemo } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import { Button, Field, Input, Textarea } from './ui'
import type { Note, NoteCreate, NoteUpdate } from '../types/note'
import { makeNoteSchema, type NoteFormData } from '../schemas/note'
import { useCreateNote, useUpdateNote } from '../hooks/queries/useNotes'
import { useFormSubmit } from '../hooks/useFormSubmit'
import { formatDateForInput } from '@/utils/dateUtils'

interface NoteFormProps {
  vin: string
  note?: Note
  onClose: () => void
  onSuccess: () => void
}

export default function NoteForm({ vin, note, onClose, onSuccess }: NoteFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!note
  const createMutation = useCreateNote(vin)
  const updateMutation = useUpdateNote(vin)

  const submitFn = useCallback(async (data: NoteFormData) => {
    const payload: NoteCreate | NoteUpdate = {
      vin,
      date: data.date,
      title: data.title,
      content: data.content,
    }

    if (isEdit) {
      await updateMutation.mutateAsync({ id: note.id, ...payload })
    } else {
      await createMutation.mutateAsync(payload as NoteCreate)
    }
  }, [isEdit, vin, note, createMutation, updateMutation])

  const { error, handleSubmit: onSubmit } = useFormSubmit(submitFn, {
    onSuccess,
    onClose,
    action: t('note.saveAction'),
  })

  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it — no fetch, no
  // reset() — so a rebuild can't discard what the user typed.
  const schema = useMemo(() => makeNoteSchema(t), [t])

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<NoteFormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      date: note?.date || formatDateForInput(),
      title: note?.title || '',
      content: note?.content || '',
    },
  })

  const title = watch('title', '')

  return (
    <FormModalWrapper
      title={isEdit ? t('note.editTitle') : t('note.createTitle')}
      onClose={onClose}
      width="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            {t('common:cancel')}
          </Button>
          <Button type="submit" form="note-form" icon={Save} loading={isSubmitting} disabled={isSubmitting}>
            {isSubmitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}
          </Button>
        </>
      }
    >
        <form id="note-form" onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <Field id="date" label={t('common:date')} required error={errors.date}>
            <Input
              id="date"
              type="date"
              {...register('date')}
              invalid={!!errors.date}
              disabled={isSubmitting}
            />
          </Field>

          <Field
            id="title"
            label={t('note.titleOptional')}
            error={errors.title}
            hint={`${title?.length ?? 0}/100 ${t('common:characters')}`}
          >
            <Input
              id="title"
              type="text"
              {...register('title')}
              placeholder={t('noteForm.titlePlaceholder')}
              invalid={!!errors.title}
              disabled={isSubmitting}
            />
          </Field>

          <Field
            id="content"
            label={t('note.content')}
            required
            error={errors.content}
            hint={t('note.freeFormHint')}
          >
            <Textarea
              id="content"
              rows={10}
              {...register('content')}
              placeholder={t('note.contentPlaceholder')}
              invalid={!!errors.content}
              disabled={isSubmitting}
            />
          </Field>
        </form>
    </FormModalWrapper>
  )
}

import { type ChangeEvent, type FormEvent, useEffect, useRef, useState } from 'react'

import {
  Avatar,
  Card,
  Disclaimer,
  ErrorNote,
  Loading,
} from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import { useAuth } from '@/store/auth'
import type { MyProfileResponse } from '@/types'

/** Longest edge of the stored photograph. Enough for a clear portrait. */
const MAX_EDGE = 512

interface FormState {
  full_name: string
  email: string
  phone_number: string
  staff_id: string
  qualification: string
  experience_years: string
}

/**
 * Downscale before upload.
 *
 * A phone photograph is several megabytes; a profile portrait needs a fraction
 * of that. Resizing in the browser keeps the stored image small, the API
 * responses light, and the upload well inside the server's size limit — which
 * is still enforced server-side regardless of what is sent.
 */
function readAsResizedDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('That file could not be read.'))
    reader.onload = () => {
      const image = new Image()
      image.onerror = () =>
        reject(new Error('That file could not be read as an image.'))
      image.onload = () => {
        const scale = Math.min(1, MAX_EDGE / Math.max(image.width, image.height))
        const width = Math.max(1, Math.round(image.width * scale))
        const height = Math.max(1, Math.round(image.height * scale))

        const canvas = document.createElement('canvas')
        canvas.width = width
        canvas.height = height
        const context = canvas.getContext('2d')
        if (!context) {
          // No canvas available: send the original and let the server decide.
          resolve(String(reader.result))
          return
        }
        context.drawImage(image, 0, 0, width, height)
        try {
          resolve(canvas.toDataURL('image/jpeg', 0.85))
        } catch {
          resolve(String(reader.result))
        }
      }
      image.src = String(reader.result)
    }
    reader.readAsDataURL(file)
  })
}

export default function MyProfilePage() {
  const { restore } = useAuth()
  const fileInput = useRef<HTMLInputElement>(null)
  const { data, loading, error, reload } = useAsync<MyProfileResponse>(() =>
    api.get('/auth/profile/'),
  )

  const [form, setForm] = useState<FormState | null>(null)
  const [photo, setPhoto] = useState<string | null>(null)
  const [photoTouched, setPhotoTouched] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState('')
  const [problem, setProblem] = useState('')

  useEffect(() => {
    if (!data) return
    const profile = data.profile
    setForm({
      full_name: profile.full_name ?? '',
      email: profile.email ?? '',
      phone_number: profile.phone_number ?? '',
      staff_id: profile.staff_id ?? '',
      qualification: profile.qualification ?? '',
      experience_years:
        profile.experience_years === null ||
        profile.experience_years === undefined
          ? ''
          : String(profile.experience_years),
    })
    setPhoto(profile.photo_url || null)
    setPhotoTouched(false)
  }, [data])

  if (loading && !data) return <Loading label="Loading your profile…" />
  if (error && !data) return <ErrorNote message={error} onRetry={reload} />
  if (!data || !form) return null

  const profile = data.profile
  const limits = data.photo_limits

  const update = (patch: Partial<FormState>) =>
    setForm((previous) => (previous ? { ...previous, ...patch } : previous))

  async function choosePhoto(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = '' // allow re-selecting the same file
    if (!file) return

    setProblem('')
    setSaved('')

    if (!limits.accepted_types.includes(file.type)) {
      setProblem(`Choose a ${limits.accepted_label} image.`)
      return
    }
    if (file.size > limits.max_bytes * 4) {
      setProblem(`That image is too large. Choose one under ${limits.max_size_label}.`)
      return
    }

    try {
      const resized = await readAsResizedDataUrl(file)
      setPhoto(resized)
      setPhotoTouched(true)
    } catch (err) {
      setProblem(
        err instanceof Error ? err.message : 'That image could not be read.',
      )
    }
  }

  function removePhoto() {
    setPhoto(null)
    setPhotoTouched(true)
    setSaved('')
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!form) return

    setSaving(true)
    setProblem('')
    setSaved('')
    try {
      const payload: Record<string, unknown> = {
        ...form,
        experience_years:
          form.experience_years.trim() === ''
            ? null
            : Number(form.experience_years),
      }
      if (photoTouched) payload.photo = photo ?? ''

      const response = await api.patch<MyProfileResponse>(
        '/auth/profile/',
        payload,
      )
      setSaved(response.message || 'Your profile has been updated.')
      setPhotoTouched(false)
      // Keeps the name in the portal header in step with the profile.
      void restore()
    } catch (err) {
      setProblem(
        err instanceof Error ? err.message : 'Your profile could not be saved.',
      )
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">My profile</h1>
        <p className="text-sm text-ink-600 mt-0.5">
          {profile.role_label}
          {profile.village_name ? ` · ${profile.village_name}` : ''}
          {profile.village_label ? ` (${profile.village_label})` : ''}
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-3 items-start">
        <Card title="Photograph">
          <div className="flex flex-col items-center gap-4 text-center">
            <Avatar
              src={photo}
              initials={profile.initials}
              name={profile.display_name}
              size="lg"
            />
            <div>
              <div className="text-sm font-medium text-ink-800">
                {profile.display_name}
              </div>
              <div className="text-xs text-ink-400">{profile.role_label}</div>
            </div>

            <input
              ref={fileInput}
              type="file"
              accept={limits.accepted_types.join(',')}
              className="hidden"
              onChange={choosePhoto}
            />
            <div className="flex flex-wrap justify-center gap-2">
              <button
                type="button"
                className="btn-ghost py-1.5"
                onClick={() => fileInput.current?.click()}
              >
                {photo ? 'Replace photo' : 'Upload photo'}
              </button>
              {photo && (
                <button
                  type="button"
                  className="btn-ghost py-1.5"
                  onClick={removePhoto}
                >
                  Remove
                </button>
              )}
            </div>
            <p className="text-xs text-ink-400">
              {limits.accepted_label}, up to {limits.max_size_label}. Larger
              images are resized before upload.
            </p>
            {photoTouched && (
              <p className="text-xs text-amber-700">
                Preview only — save below to keep this photograph.
              </p>
            )}
            <p className="text-xs text-ink-400 border-t border-ink-200 pt-3">
              Your photograph is visible to the health officer for your area and
              to your administrator. It is not published anywhere public.
            </p>
          </div>
        </Card>

        <Card title="Professional details" className="lg:col-span-2">
          <form onSubmit={submit} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="label" htmlFor="full_name">
                  Full name
                </label>
                <input
                  id="full_name"
                  className="input"
                  value={form.full_name}
                  onChange={(event) => update({ full_name: event.target.value })}
                />
              </div>
              <div>
                <label className="label" htmlFor="staff_id">
                  Employee / worker ID
                </label>
                <input
                  id="staff_id"
                  className="input"
                  value={form.staff_id}
                  onChange={(event) => update({ staff_id: event.target.value })}
                />
              </div>
              <div>
                <label className="label" htmlFor="phone_number">
                  Contact number
                </label>
                <input
                  id="phone_number"
                  className="input"
                  inputMode="tel"
                  value={form.phone_number}
                  onChange={(event) =>
                    update({ phone_number: event.target.value })
                  }
                />
              </div>
              <div>
                <label className="label" htmlFor="email">
                  Work email
                </label>
                <input
                  id="email"
                  type="email"
                  className="input"
                  value={form.email}
                  onChange={(event) => update({ email: event.target.value })}
                />
              </div>
              <div>
                <label className="label" htmlFor="qualification">
                  Qualification
                </label>
                <input
                  id="qualification"
                  className="input"
                  value={form.qualification}
                  onChange={(event) =>
                    update({ qualification: event.target.value })
                  }
                />
              </div>
              <div>
                <label className="label" htmlFor="experience_years">
                  Years of experience
                </label>
                <input
                  id="experience_years"
                  type="number"
                  min={0}
                  max={60}
                  className="input"
                  value={form.experience_years}
                  onChange={(event) =>
                    update({ experience_years: event.target.value })
                  }
                />
              </div>
            </div>

            {/* Read-only: assignment and sign-in are administered, not
                self-selected. */}
            <div className="rounded-md border border-ink-200 bg-ink-50 px-3 py-2">
              <div className="label mb-1">Assigned by your administrator</div>
              <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
                <div className="flex justify-between gap-3">
                  <dt className="text-ink-400">Role</dt>
                  <dd className="text-ink-800">{profile.role_label}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-ink-400">Village / area</dt>
                  <dd className="text-ink-800">
                    {profile.village_name ?? 'District-wide'}
                  </dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-ink-400">Facility</dt>
                  <dd className="text-ink-800">
                    {profile.facility_name ?? '—'}
                  </dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-ink-400">Username</dt>
                  <dd className="font-mono text-ink-800">{profile.username}</dd>
                </div>
              </dl>
            </div>

            {problem && <ErrorNote message={problem} />}
            {saved && (
              <p className="rounded-md border border-care-200 bg-care-50 px-3 py-2 text-sm text-care-800">
                {saved}
              </p>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <button type="submit" className="btn-care" disabled={saving}>
                {saving ? 'Saving…' : 'Save profile'}
              </button>
              {profile.profile_updated_at && (
                <span className="text-xs text-ink-400">
                  Last updated{' '}
                  {new Date(profile.profile_updated_at).toLocaleString()}
                </span>
              )}
            </div>

            <p className="text-xs text-ink-400">{data.note}</p>
            <Disclaimer />
          </form>
        </Card>
      </div>
    </div>
  )
}

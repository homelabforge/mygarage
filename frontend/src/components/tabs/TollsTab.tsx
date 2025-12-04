import { useState, useEffect } from 'react'
import api from '../../services/api'
import TollTagList from '../TollTagList'
import TollTagForm from '../TollTagForm'
import TollTransactionList from '../TollTransactionList'
import TollTransactionForm from '../TollTransactionForm'
import type { TollTag, TollTransaction } from '../../types/toll'

interface TollsTabProps {
  vin: string
}

export default function TollsTab({ vin }: TollsTabProps) {
  const [showTagForm, setShowTagForm] = useState(false)
  const [showTransactionForm, setShowTransactionForm] = useState(false)
  const [editTag, setEditTag] = useState<TollTag | undefined>()
  const [editTransaction, setEditTransaction] = useState<TollTransaction | undefined>()
  const [tollTags, setTollTags] = useState<TollTag[]>([])
  const [refreshTagsKey, setRefreshTagsKey] = useState(0)
  const [refreshTransactionsKey, setRefreshTransactionsKey] = useState(0)

  // Fetch toll tags
  useEffect(() => {
    const fetchTollTags = async () => {
      try {
        const response = await api.get(`/vehicles/${vin}/toll-tags`)
        setTollTags(response.data.toll_tags || [])
      } catch {
        // Removed console.error
      }
    }
    fetchTollTags()
  }, [vin, refreshTagsKey])

  // Toll Tag handlers
  const handleAddTagClick = () => {
    setEditTag(undefined)
    setShowTagForm(true)
  }

  const handleEditTagClick = (tag: TollTag) => {
    setEditTag(tag)
    setShowTagForm(true)
  }

  const handleCloseTagForm = () => {
    setShowTagForm(false)
    setEditTag(undefined)
  }

  const handleTagSuccess = () => {
    setRefreshTagsKey(k => k + 1)
    handleCloseTagForm()
  }

  // Toll Transaction handlers
  const handleAddTransactionClick = () => {
    setEditTransaction(undefined)
    setShowTransactionForm(true)
  }

  const handleEditTransactionClick = (transaction: TollTransaction) => {
    setEditTransaction(transaction)
    setShowTransactionForm(true)
  }

  const handleCloseTransactionForm = () => {
    setShowTransactionForm(false)
    setEditTransaction(undefined)
  }

  const handleTransactionSuccess = () => {
    setRefreshTransactionsKey(k => k + 1)
    handleCloseTransactionForm()
  }

  return (
    <div className="space-y-8">
      {/* Toll Tags Section */}
      <section>
        <TollTagList
          vin={vin}
          onAddClick={handleAddTagClick}
          onEditClick={handleEditTagClick}
          key={refreshTagsKey}
        />
      </section>

      {/* Divider */}
      <div className="border-t border-garage-border"></div>

      {/* Toll Transactions Section */}
      <section>
        <TollTransactionList
          vin={vin}
          tollTags={tollTags}
          onAddClick={handleAddTransactionClick}
          onEditClick={handleEditTransactionClick}
          key={refreshTransactionsKey}
        />
      </section>

      {/* Forms */}
      {showTagForm && (
        <TollTagForm
          vin={vin}
          tag={editTag}
          onClose={handleCloseTagForm}
          onSuccess={handleTagSuccess}
        />
      )}

      {showTransactionForm && (
        <TollTransactionForm
          vin={vin}
          tollTags={tollTags}
          transaction={editTransaction}
          onClose={handleCloseTransactionForm}
          onSuccess={handleTransactionSuccess}
        />
      )}
    </div>
  )
}

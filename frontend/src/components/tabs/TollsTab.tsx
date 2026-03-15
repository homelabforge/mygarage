import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useTollTags } from '../../hooks/queries/useTollRecords'
import TollTagList from '../TollTagList'
import TollTagForm from '../TollTagForm'
import TollTransactionList from '../TollTransactionList'
import TollTransactionForm from '../TollTransactionForm'
import type { TollTag, TollTransaction } from '../../types/toll'

interface TollsTabProps {
  vin: string
}

export default function TollsTab({ vin }: TollsTabProps) {
  const queryClient = useQueryClient()
  const { data: tagsData } = useTollTags(vin)
  const tollTags = tagsData?.toll_tags ?? []
  const [showTagForm, setShowTagForm] = useState(false)
  const [showTransactionForm, setShowTransactionForm] = useState(false)
  const [editTag, setEditTag] = useState<TollTag | undefined>()
  const [editTransaction, setEditTransaction] = useState<TollTransaction | undefined>()

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
    queryClient.invalidateQueries({ queryKey: ['tollTags', vin] })
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
    queryClient.invalidateQueries({ queryKey: ['tollTransactions', vin] })
    queryClient.invalidateQueries({ queryKey: ['tollTransactionSummary', vin] })
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
        />
      </section>

      {/* Divider */}
      <div className="border-t border-garage-border"></div>

      {/* Toll Transactions Section */}
      <section>
        <TollTransactionList
          vin={vin}
          onAddClick={handleAddTransactionClick}
          onEditClick={handleEditTransactionClick}
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
